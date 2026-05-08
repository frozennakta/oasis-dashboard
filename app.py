import streamlit as st
import requests
import os
from dotenv import load_dotenv

load_dotenv()

WP_URL = os.getenv("WP_URL", "").rstrip("/")
WP_USER = os.getenv("WP_USER", "")
WP_APP_PASSWORD = os.getenv("WP_APP_PASSWORD", "")
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "oasis1234")

st.set_page_config(page_title="Hanoi King 황순창 전용 매물 등록", page_icon="🏡", layout="centered")
st.title("🏡 Hanoi King 황순창 전용 매물 등록")

if not WP_URL or not WP_USER or not WP_APP_PASSWORD:
    st.error("⚠️ .env 파일에 WP_URL, WP_USER, WP_APP_PASSWORD를 설정해주세요.")
    st.stop()

pw = st.text_input("비밀번호를 입력하세요", type="password")
if pw != DASHBOARD_PASSWORD:
    st.stop()

auth = (WP_USER, WP_APP_PASSWORD)

@st.cache_data(ttl=3600)
def fetch_terms(taxonomy):
    resp = requests.get(
        f"{WP_URL}/wp-json/wp/v2/{taxonomy}?per_page=100",
        auth=auth,
    )
    if resp.status_code == 200:
        return {item["name"]: item["id"] for item in resp.json()}
    return {}

cities = fetch_terms("property_state")
districts = fetch_terms("property_city")
areas = fetch_terms("property_area")

with st.form("property_form"):
    st.subheader("매물 정보")

    title = st.text_input("매물 제목 *", placeholder="예: Gateway Thao Dien | 2BR River View")
    description = st.text_area("상세 설명", placeholder="매물 상세 설명을 입력하세요...", height=150)

    col1, col2 = st.columns(2)
    with col1:
        currency = st.selectbox("통화", ["USD", "VND"])
        price = st.number_input(
            "월세 *",
            min_value=0,
            step=100 if currency == "USD" else 1000000,
            format="%d",
        )
    with col2:
        area_size = st.number_input("면적 (㎡)", min_value=0, step=1)
        deposit_months = st.number_input("보증금 (개월)", min_value=0, max_value=12, step=1, value=2)

    col3, col4 = st.columns(2)
    with col3:
        bedrooms = st.number_input("침실 수", min_value=0, max_value=20, step=1)
    with col4:
        bathrooms = st.number_input("욕실 수", min_value=0, max_value=20, step=1)

    st.subheader("위치")
    col5, col6, col7 = st.columns(3)
    with col5:
        city_name = st.selectbox("도시", ["선택 안함"] + list(cities.keys()))
    with col6:
        district_name = st.selectbox("구역 (군)", ["선택 안함"] + list(districts.keys()))
    with col7:
        area_name = st.selectbox("아파트 단지", ["선택 안함"] + list(areas.keys()))

    address = st.text_input("상세 주소", placeholder="예: District 2, Thao Dien, Ho Chi Minh City")

    st.subheader("이미지 업로드")
    images = st.file_uploader(
        "이미지 선택 (여러 장 가능)",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True,
    )

    submitted = st.form_submit_button("📤 매물 등록하기", use_container_width=True)

if submitted:
    if not title:
        st.error("매물 제목을 입력해주세요.")
        st.stop()

    image_ids = []
    featured_id = None

    if images:
        st.info(f"이미지 {len(images)}장 업로드 중...")
        progress = st.progress(0)
        for i, img in enumerate(images):
            safe_name = img.name.encode("ascii", "ignore").decode("ascii") or f"image_{i}.jpg"
            headers = {
                "Content-Disposition": f'attachment; filename="{safe_name}"',
                "Content-Type": img.type,
            }
            resp = requests.post(
                f"{WP_URL}/wp-json/wp/v2/media",
                headers=headers,
                data=img.read(),
                auth=auth,
            )
            if resp.status_code in (200, 201):
                media_id = resp.json().get("id")
                image_ids.append(media_id)
                if i == 0:
                    featured_id = media_id
            else:
                st.error(f"❌ 이미지 업로드 실패 [{img.name}] — HTTP {resp.status_code}: {resp.text[:200]}")
                st.stop()
            progress.progress((i + 1) / len(images))
        st.success(f"✅ 이미지 {len(image_ids)}장 업로드 완료")

    price_str = f"{int(price):,} {currency}/월"

    taxonomies = {}
    if city_name != "선택 안함":
        taxonomies["property_state"] = [cities[city_name]]
    if district_name != "선택 안함":
        taxonomies["property_city"] = [districts[district_name]]
    if area_name != "선택 안함":
        taxonomies["property_area"] = [areas[area_name]]

    with st.spinner("매물 등록 중..."):
        payload = {
            "title": title,
            "content": description,
            "status": "publish",
            "meta": {
                "fave_property_price": str(int(price)),
                "fave_property_price_prefix": currency,
                "fave_property_size": str(area_size),
                "fave_property_bedrooms": str(bedrooms),
                "fave_property_bathrooms": str(bathrooms),
                "fave_property_address": address,
                "fave_property_images": image_ids,
                "fave_property_sec_deposit": str(deposit_months),
            },
            **taxonomies,
        }
        if featured_id:
            payload["featured_media"] = featured_id

        resp = requests.post(
            f"{WP_URL}/wp-json/wp/v2/properties",
            json=payload,
            auth=auth,
        )

    if resp.status_code in (200, 201):
        data = resp.json()
        link = data.get("link", "")
        st.success(f"🎉 매물 등록 완료! ({price_str}, 보증금 {deposit_months}개월)")
        st.markdown(f"[👉 등록된 매물 보기]({link})")
    else:
        st.error(f"❌ 매물 발행 실패 — HTTP {resp.status_code}: {resp.text[:300]}")
