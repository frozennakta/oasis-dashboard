"""
오아시스VN 매물 등록 대시보드 (Streamlit)
- 도시 → 군 → 단지 cascading 선택
- 단지 검색 가능
- 매물 제목 자동 생성 (단지 + 침실수 + 가격)
- 이미지 미리보기 + 첫 사진 자동 대표
- 가구/연식/주차 등 Houzez 추가 메타 필드
- 등록 후 "또 등록하기" 버튼
"""
import streamlit as st
import requests
import os
import json
import re
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

WP_URL = os.getenv("WP_URL", "").rstrip("/")
WP_USER = os.getenv("WP_USER", "")
WP_APP_PASSWORD = os.getenv("WP_APP_PASSWORD", "")
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "oasis1234")

st.set_page_config(page_title="오아시스VN 매물 등록", page_icon="🏡", layout="centered")

# ────────────────────────────────────────────────────────────────
# 인증
# ────────────────────────────────────────────────────────────────
if not WP_URL or not WP_USER or not WP_APP_PASSWORD:
    st.error("⚠️ dashboard/.env 파일에 WP_URL, WP_USER, WP_APP_PASSWORD를 설정해주세요.")
    st.stop()

if "auth_ok" not in st.session_state:
    st.session_state.auth_ok = False

if not st.session_state.auth_ok:
    st.title("🏡 오아시스VN 매물 등록")
    pw = st.text_input("비밀번호", type="password")
    if pw == DASHBOARD_PASSWORD:
        st.session_state.auth_ok = True
        st.rerun()
    elif pw:
        st.error("비밀번호가 틀렸습니다.")
    st.stop()

auth = (WP_USER, WP_APP_PASSWORD)

# ────────────────────────────────────────────────────────────────
# 데이터 로드: 분류 매핑 (taxonomy.json)  +  WP 서버의 term ID
# ────────────────────────────────────────────────────────────────
TAXONOMY_FILE = Path(__file__).parent / "taxonomy.json"
TAXONOMY = json.loads(TAXONOMY_FILE.read_text(encoding="utf-8"))


@st.cache_data(ttl=3600)
def fetch_terms(taxonomy: str) -> dict:
    """slug → term_id 매핑."""
    resp = requests.get(f"{WP_URL}/wp-json/wp/v2/{taxonomy}?per_page=100", auth=auth)
    if resp.status_code != 200:
        return {}
    return {item["slug"]: item["id"] for item in resp.json()}


with st.spinner("분류 정보 동기화 중..."):
    city_ids = fetch_terms("property_state")
    district_ids = fetch_terms("property_city")
    area_ids = fetch_terms("property_area")

# 서버에 분류 텀이 없으면 알림
if not city_ids or not district_ids or not area_ids:
    st.error("⚠️ 분류 텀이 부족합니다. rebuild_taxonomies.py 를 먼저 실행하세요.")
    st.stop()

# ────────────────────────────────────────────────────────────────
# 헤더
# ────────────────────────────────────────────────────────────────
st.title("🏡 오아시스VN 매물 등록")
st.caption(f"📊 등록 가능: 도시 {len(city_ids)} / 군·구 {len(district_ids)} / 단지 {len(area_ids)}")

# 등록 직후 결과 표시 (rerun 후에도 유지)
if "last_result" in st.session_state:
    r = st.session_state.last_result
    st.success(f"🎉 등록 완료: **{r['title']}** ({r['price_str']}, 사진 {r['photo_count']}장)")
    cols = st.columns(2)
    with cols[0]:
        st.markdown(f"[👉 사이트에서 보기]({r['link']})")
    with cols[1]:
        st.markdown(f"[✏️ wp-admin에서 편집]({WP_URL}/wp-admin/post.php?post={r['id']}&action=edit)")
    if st.button("➕ 새 매물 등록하기", type="primary", use_container_width=True):
        del st.session_state.last_result
        st.rerun()
    st.divider()

# ────────────────────────────────────────────────────────────────
# 폼: 위치 (cascading) — st.form 밖에 두기 (실시간 종속 select)
# ────────────────────────────────────────────────────────────────
st.subheader("📍 위치 선택")

cities_with_label = {c["label"]: c["slug"] for c in TAXONOMY["cities"]}
city_label = st.selectbox("도시", [""] + list(cities_with_label.keys()),
                          format_func=lambda x: "— 선택 —" if x == "" else x,
                          key="city")
city_slug = cities_with_label.get(city_label)

# 군: 선택한 도시의 것만
filtered_districts = [d for d in TAXONOMY["districts"] if d["city"] == city_slug] if city_slug else []
district_options = {"": ""} | {d["label"]: d["slug"] for d in filtered_districts}
district_label = st.selectbox(
    "군 / 구",
    list(district_options.keys()),
    format_func=lambda x: "— 도시를 먼저 선택 —" if not city_slug and x == "" else ("— 선택 —" if x == "" else x),
    key="district",
    disabled=not city_slug,
)
district_slug = district_options.get(district_label, "")

# 단지: 선택한 군의 것만 + 검색
filtered_areas = [a for a in TAXONOMY["areas"] if a["district"] == district_slug] if district_slug else []
area_options = {"": ""} | {a["name"]: a["slug"] for a in filtered_areas}
area_help = "검색 가능: 단지명 일부만 입력해도 필터됨"
area_label = st.selectbox(
    "아파트 단지",
    list(area_options.keys()),
    format_func=lambda x: "— 군을 먼저 선택 —" if not district_slug and x == "" else (
        "— 선택 —" if x == "" else x),
    key="area",
    disabled=not district_slug,
    help=area_help,
)
area_slug = area_options.get(area_label, "")
area_name = area_label if area_slug else ""

# ────────────────────────────────────────────────────────────────
# 폼: 매물 상세
# ────────────────────────────────────────────────────────────────
with st.form("property_form", clear_on_submit=False):
    st.subheader("🏢 매물 상세")

    c1, c2 = st.columns([2, 1])
    with c1:
        bedrooms = st.number_input("침실 수", min_value=0, max_value=20, step=1, value=2)
    with c2:
        bathrooms = st.number_input("욕실 수", min_value=0, max_value=20, step=1, value=2)

    c3, c4, c5 = st.columns(3)
    with c3:
        currency = st.selectbox("통화", ["USD", "VND"], index=0)
    with c4:
        price = st.number_input(
            f"월세 ({currency}) *",
            min_value=0, step=100 if currency == "USD" else 1_000_000, value=0, format="%d",
        )
    with c5:
        area_size = st.number_input("면적 (㎡)", min_value=0, step=1, value=0)

    c6, c7 = st.columns(2)
    with c6:
        deposit_months = st.number_input("보증금 (개월)", min_value=0, max_value=12, step=1, value=2)
    with c7:
        year_built = st.number_input("준공 연도 (선택)", min_value=0, max_value=2030, step=1, value=0,
                                     help="0 = 입력 안함")

    c8, c9 = st.columns(2)
    with c8:
        furnishing = st.selectbox(
            "가구 상태",
            ["선택 안함", "Fully Furnished", "Semi-Furnished", "Unfurnished"],
            help="Fully = 풀옵션, Semi = 기본 가구만, Unfurnished = 빈집",
        )
    with c9:
        view = st.text_input("뷰 / 특징", placeholder="예: River View / City View / Pool View")

    # 매물 제목
    st.subheader("📝 매물 제목 & 설명")
    suggested = ""
    if area_name and bedrooms > 0 and price > 0:
        bedroom_label = f"{bedrooms}BR" if bedrooms < 10 else "Studio"
        view_part = f" | {view}" if view else ""
        price_part = f" | {currency} {int(price):,}/month"
        suggested = f"{area_name} | {bedroom_label}{view_part}{price_part}"

    title = st.text_input(
        "매물 제목 *",
        value=st.session_state.get("title_field", suggested),
        placeholder=suggested or "예: Gateway Thao Dien | 2BR River View | USD 1,500/month",
        key="title_field",
        help="단지·침실·뷰·가격 정보로 자동 생성됨. 자유롭게 수정 가능",
    )

    description = st.text_area(
        "상세 설명",
        placeholder="매물에 대한 자유로운 설명 (시설, 위치 장점, 외국인 편의 등)",
        height=180,
    )

    address = st.text_input("상세 주소 (선택)",
                            placeholder="예: 159 Xa Lo Ha Noi, Thao Dien Ward, District 2, HCMC")

    # 이미지
    st.subheader("📷 사진 업로드")
    st.caption("💡 PC: 파일 탐색기에서 **Ctrl+A** → 드래그   ·   모바일: 사진첩 다중 선택   ·   첫 번째 사진이 대표 사진이 됩니다")
    images = st.file_uploader(
        "이미지 (여러 장 가능)",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True,
    )

    if images:
        st.info(f"📷 {len(images)}장 선택됨 — 첫 번째가 대표 사진")
        # 미리보기 (최대 8장)
        preview_cols = st.columns(4)
        for i, img in enumerate(images[:8]):
            with preview_cols[i % 4]:
                st.image(img, caption=f"{'⭐' if i == 0 else ''} #{i+1}", width=160)
        if len(images) > 8:
            st.caption(f"... 외 {len(images) - 8}장 더 (등록 시 모두 업로드됨)")

    submitted = st.form_submit_button("📤 매물 등록하기", type="primary", use_container_width=True)


# ────────────────────────────────────────────────────────────────
# 등록 처리
# ────────────────────────────────────────────────────────────────
if submitted:
    # 검증
    errors = []
    if not title.strip():
        errors.append("매물 제목을 입력해주세요.")
    if price <= 0:
        errors.append("월세 가격을 입력해주세요.")
    if not city_slug:
        errors.append("도시를 선택해주세요.")
    if not district_slug:
        errors.append("군/구를 선택해주세요.")
    if not area_slug:
        errors.append("아파트 단지를 선택해주세요.")
    if errors:
        for e in errors:
            st.error("⚠️ " + e)
        st.stop()

    # ── 이미지 업로드 ──
    image_ids = []
    featured_id = None
    if images:
        with st.status(f"📷 사진 {len(images)}장 업로드 중...", expanded=True) as status:
            progress = st.progress(0)
            for i, img in enumerate(images):
                safe = re.sub(r"[^A-Za-z0-9._-]", "_", img.name) or f"image_{i+1}.jpg"
                # 단지 슬러그 + 인덱스로 파일명 (SEO 친화)
                ext = Path(safe).suffix or ".jpg"
                pretty_name = f"{area_slug}-{datetime.now():%Y%m%d}-{i+1:02d}{ext}"
                headers = {
                    "Content-Disposition": f'attachment; filename="{pretty_name}"',
                    "Content-Type": img.type or "image/jpeg",
                }
                resp = requests.post(
                    f"{WP_URL}/wp-json/wp/v2/media",
                    headers=headers, data=img.read(), auth=auth,
                )
                if resp.status_code in (200, 201):
                    mid = resp.json().get("id")
                    image_ids.append(mid)
                    if i == 0:
                        featured_id = mid
                    st.write(f"  ✅ #{i+1}/{len(images)} — media ID {mid}")
                else:
                    st.error(f"❌ 사진 #{i+1} 업로드 실패 — HTTP {resp.status_code}: {resp.text[:200]}")
                    st.stop()
                progress.progress((i + 1) / len(images))
            status.update(label=f"✅ 사진 {len(image_ids)}장 업로드 완료", state="complete")

    # ── 메타 페이로드 (Houzez 표준 메타만) ──
    meta = {
        "fave_property_price": str(int(price)),
        "fave_property_price_prefix": currency,
        "fave_property_size": str(int(area_size)),
        "fave_property_bedrooms": str(int(bedrooms)),
        "fave_property_bathrooms": str(int(bathrooms)),
        "fave_property_address": address.strip(),
        "fave_property_sec_deposit": str(int(deposit_months)),
    }
    if image_ids:
        meta["fave_property_images"] = image_ids
    if year_built > 0:
        meta["fave_property_year"] = str(int(year_built))
    # furnishing/view 는 Houzez 표준이 아니라 wp-admin에 입력칸이 없으므로
    # 메타로도 저장하되 description 앞부분에 강조 라인으로도 자동 삽입
    if furnishing != "선택 안함":
        meta["fave_property_furnishing"] = furnishing
    if view.strip():
        meta["fave_property_view"] = view.strip()

    # ── description 자동 보강 ──
    enrichment_lines = []
    badge_parts = []
    if area_name:
        badge_parts.append(area_name)
    if bedrooms > 0:
        badge_parts.append(f"{int(bedrooms)} bed")
    if bathrooms > 0:
        badge_parts.append(f"{int(bathrooms)} bath")
    if area_size > 0:
        badge_parts.append(f"{int(area_size)} ㎡")
    if furnishing != "선택 안함":
        badge_parts.append(furnishing)
    if view.strip():
        badge_parts.append(view.strip())
    if year_built > 0:
        badge_parts.append(f"Built {int(year_built)}")
    if deposit_months > 0:
        badge_parts.append(f"Deposit {int(deposit_months)} mo")

    if badge_parts:
        enrichment_lines.append(" · ".join(badge_parts))
    if address.strip():
        enrichment_lines.append(f"📍 {address.strip()}")

    enriched_description = ("\n\n".join(enrichment_lines) + "\n\n" + description.strip()).strip() if enrichment_lines else description.strip()

    payload = {
        "title": title.strip(),
        "content": enriched_description,
        "excerpt": " · ".join(badge_parts)[:200] if badge_parts else description.strip()[:200],
        "meta": meta,
        "property_state": [city_ids[city_slug]],
        "property_city":  [district_ids[district_slug]],
        "property_area":  [area_ids[area_slug]],
    }
    if featured_id:
        payload["featured_media"] = featured_id

    # ── 등록 요청 ──
    with st.spinner("📡 매물 등록 중..."):
        resp = requests.post(
            f"{WP_URL}/wp-json/oasis/v1/property",
            json=payload, auth=auth, timeout=60,
        )

    if resp.status_code in (200, 201):
        data = resp.json()
        price_str = f"{currency} {int(price):,}/월"
        st.session_state.last_result = {
            "id": data.get("property_id"),
            "title": title.strip(),
            "link": data.get("link", ""),
            "price_str": price_str,
            "photo_count": len(image_ids),
        }
        # 다음 등록을 위해 제목 필드 초기화 (자동 생성 다시 받기)
        st.session_state.title_field = ""
        st.rerun()
    else:
        st.error(f"❌ 매물 등록 실패 — HTTP {resp.status_code}")
        st.code(resp.text[:600])
