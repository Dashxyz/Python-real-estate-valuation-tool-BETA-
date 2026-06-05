                  # Made by Yahya Ahmad AKA, Dashxyz
      # Homelytics Pakistan V5
# Improvements: parallel image analysis, global model instances, additional property inputs,
# unit converters, multi-query market research, deterministic price/sqft model,
# society premium detection, location confidence, structured output sections,
# request logging, user feedback, validation for land_size, progress status

import google.generativeai as genai
import gradio as gr
from PIL import Image
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
from ddgs.ddgs import DDGS
import re
import time
import os
import json
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
GOOGLE_AI_API_KEY = os.environ.get("GOOGLE_AI_API_KEY", "")
if not GOOGLE_AI_API_KEY:
    print("WARNING: GOOGLE_AI_API_KEY is not set. The app will not work.")
genai.configure(api_key=GOOGLE_AI_API_KEY)

# Global model instances — instantiated once at startup for speed
VISION_MODEL    = genai.GenerativeModel('gemini-1.5-flash-latest')
VALUATION_MODEL = genai.GenerativeModel('gemini-1.5-flash-latest')

# In-memory search cache
_search_cache = {}

# Request log (in-memory, appended each run)
_request_log = []

# ---------------------------------------------------------------------------
# Unit Converters
# ---------------------------------------------------------------------------
def marla_to_sqft(marla):   return marla * 272.25
def kanal_to_sqft(kanal):   return kanal * 5445.0
def sqft_to_marla(sqft):    return sqft / 272.25
def sqft_to_kanal(sqft):    return sqft / 5445.0

def land_to_sqft_pk(size, unit):
    if unit == "Marla":  return marla_to_sqft(size)
    if unit == "Kanal":  return kanal_to_sqft(size)
    return size  # already sqft

# ---------------------------------------------------------------------------
# Society / Premium Area Detection (PK)
# ---------------------------------------------------------------------------
PREMIUM_SOCIETIES = {
    "dha":      0.35,
    "bahria":   0.25,
    "gulberg":  0.20,
    "model town": 0.18,
    "johar town": 0.10,
    "cantt":    0.15,
    "clifton":  0.30,
    "defence":  0.35,
    "f-6":      0.25,
    "f-7":      0.25,
    "f-8":      0.20,
    "e-7":      0.22,
}

def detect_society_premium(address):
    addr_lower = address.lower()
    for society, premium in PREMIUM_SOCIETIES.items():
        if society in addr_lower:
            return society.upper(), premium
    return None, 0.0

# ---------------------------------------------------------------------------
# Base Price-Per-Sqft Model (PKR) — deterministic fallback
# ---------------------------------------------------------------------------
BASE_PRICE_SQFT_PKR = {
    "Lahore":     {"House": 12000, "Apartment": 10000, "Farmhouse": 6000,  "Mall": 25000, "Warehouse": 8000},
    "Karachi":    {"House": 14000, "Apartment": 12000, "Farmhouse": 5000,  "Mall": 28000, "Warehouse": 9000},
    "Islamabad":  {"House": 18000, "Apartment": 15000, "Farmhouse": 8000,  "Mall": 35000, "Warehouse": 11000},
    "Rawalpindi": {"House": 10000, "Apartment": 8000,  "Farmhouse": 4500,  "Mall": 20000, "Warehouse": 7000},
    "Faisalabad": {"House": 8000,  "Apartment": 7000,  "Farmhouse": 3500,  "Mall": 18000, "Warehouse": 6000},
    "Peshawar":   {"House": 9000,  "Apartment": 7500,  "Farmhouse": 4000,  "Mall": 19000, "Warehouse": 6500},
}
PLOT_PRICE_PER_SQFT_PKR = {
    "Lahore": 9000, "Karachi": 11000, "Islamabad": 14000,
    "Rawalpindi": 7000, "Faisalabad": 5500, "Peshawar": 6000,
}
CONDITION_MULTIPLIERS = {"Excellent": 1.20, "Good": 1.05, "Average": 1.00, "Needs Renovation": 0.80}
AGE_MULTIPLIERS = {
    "Brand New (0-2 yrs)": 1.15, "Recent (3-10 yrs)": 1.05,
    "Established (11-20 yrs)": 0.95, "Old (20+ yrs)": 0.85
}

def compute_deterministic_estimate(city, property_type, sq_ft, land_sqft, condition, year_built_category, society_premium):
    try:
        multiplier = CONDITION_MULTIPLIERS.get(condition, 1.0) * AGE_MULTIPLIERS.get(year_built_category, 1.0) * (1 + society_premium)
        if property_type == "Plot":
            base = PLOT_PRICE_PER_SQFT_PKR.get(city, 8000)
            total = base * land_sqft * multiplier
            price_per_sqft = base * multiplier
        else:
            base = BASE_PRICE_SQFT_PKR.get(city, {}).get(property_type, 10000)
            total = base * sq_ft * multiplier
            price_per_sqft = base * multiplier
        low  = total * 0.88
        high = total * 1.12
        return round(low), round(high), round(price_per_sqft)
    except Exception as e:
        print(f"Deterministic estimate error: {e}")
        return None, None, None

def format_pkr(amount):
    """Format number in Pakistani comma style (e.g. 2,50,00,000)"""
    s = str(int(amount))
    if len(s) <= 3:
        return s
    result = s[-3:]
    s = s[:-3]
    while len(s) > 2:
        result = s[-2:] + "," + result
        s = s[:-2]
    if s:
        result = s + "," + result
    return result

# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
def search_market_prices_ddg(query, region='pk-en'):
    if query in _search_cache:
        print(f"CACHE HIT: '{query}'")
        return _search_cache[query]
    try:
        results = DDGS().text(query, region=region, max_results=5)
        if not results:
            return "No recent market data found..."
        snippets = [
            f"Title: {item.get('title','N/A')}\nSnippet: {item.get('body','N/A')}\n"
            for item in results
        ]
        result_text = "\n---\n".join(snippets)
        _search_cache[query] = result_text
        return result_text
    except Exception as e:
        print(f"DDG Search Error: {e}")
        return "Could not perform market research."

def multi_query_search(city, property_type, sq_ft, land_size, land_unit):
    """Run multiple targeted searches for richer market data"""
    queries = []
    if property_type == "Plot":
        queries = [
            f"plot price per marla {city} Pakistan 2024 2025",
            f"residential plot rates {city} Pakistan latest",
        ]
    else:
        queries = [
            f"{property_type} price per sq ft {city} Pakistan 2024 2025",
            f"property rates {city} Pakistan {property_type} latest",
            f"real estate market trend {city} Pakistan 2024",
        ]
    results = []
    for q in queries:
        r = search_market_prices_ddg(q)
        if r and "No recent" not in r and "Could not" not in r:
            results.append(f"[Query: {q}]\n{r}")
    return "\n\n===\n\n".join(results) if results else "No market data found."

# ---------------------------------------------------------------------------
# Geocoding
# ---------------------------------------------------------------------------
def get_city_from_nominatim(location):
    if not location or not location.address:
        return None
    full_address = location.address.lower()
    cities = ["lahore","karachi","islamabad","rawalpindi","faisalabad","peshawar","multan","quetta","sialkot","gujranwala"]
    for part in [p.strip() for p in full_address.split(',')]:
        for city in cities:
            if city in part:
                return city.title()
    return None

def get_location_confidence(location, address):
    if not location:
        return "Low", "Address could not be geocoded."
    raw = location.raw.get('address', {})
    has_street    = bool(raw.get('road') or raw.get('house_number'))
    has_district  = bool(raw.get('suburb') or raw.get('neighbourhood') or raw.get('city_district'))
    has_city      = bool(raw.get('city') or raw.get('town'))
    score = sum([has_street, has_district, has_city])
    if score == 3: return "High",   "Street, district, and city all confirmed."
    if score == 2: return "Medium", "City and district confirmed; street-level precision may vary."
    return "Low", "Only approximate location matched. Verify the address."

def find_location_sequentially(geolocator, address):
    attempts = [
        f"{address}, Pakistan",
        address,
    ]
    match = re.search(r"((?:DHA|Bahria|Model|Gulberg|Johar)\s+(?:Town|City|Phase|Sector|Enclave)[\s\w\d-]+)", address, re.IGNORECASE)
    if match:
        area = match.group(1).strip()
        for city_kw in ["lahore","karachi","islamabad"]:
            if city_kw in address.lower():
                area += f", {city_kw.title()}"
                break
        attempts.insert(1, f"{area}, Pakistan")
    simplified = ", ".join(address.split(',')[-2:]) if ',' in address else " ".join(address.split()[-3:])
    attempts.append(f"{simplified}, Pakistan")

    for i, attempt in enumerate(attempts, 1):
        print(f"GEOCODING (ATTEMPT {i}): '{attempt}'")
        try:
            loc = geolocator.geocode(attempt, country_codes="pk", language='en')
            if loc:
                return loc
            time.sleep(0.8)
        except (GeocoderTimedOut, GeocoderServiceError) as e:
            print(f"GEOCODING ERROR attempt {i}: {e}")
    return None

# ---------------------------------------------------------------------------
# Image Analysis — parallel
# ---------------------------------------------------------------------------
def analyze_single_image(img):
    prompt = (
        "Analyze this property image from Pakistan. "
        "Describe: (1) overall condition (Excellent/Good/Average/Needs Renovation), "
        "(2) architectural style and finish quality, "
        "(3) specific features visible (pool, garden, parking, extra floors, modern kitchen, etc.), "
        "(4) any red flags or issues that would negatively affect value."
    )
    return VISION_MODEL.generate_content([prompt, img]).text

def analyze_images_parallel(photos):
    if not photos:
        return "No photos provided."
    pil_images = [Image.open(p.name) for p in photos]
    descriptions = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(analyze_single_image, img): i for i, img in enumerate(pil_images)}
        for future in as_completed(futures):
            try:
                descriptions.append(future.result())
            except Exception as e:
                descriptions.append(f"Image analysis failed: {e}")
    return "\n\n---\n\n".join(descriptions)

# ---------------------------------------------------------------------------
# Request Logger
# ---------------------------------------------------------------------------
def log_request(address, property_type, city, estimated_low, estimated_high):
    entry = {
        "timestamp":    datetime.datetime.now().isoformat(),
        "address":      address,
        "property_type": property_type,
        "city":         city,
        "est_low_pkr":  estimated_low,
        "est_high_pkr": estimated_high,
    }
    _request_log.append(entry)
    print(f"LOG: {json.dumps(entry)}")

# ---------------------------------------------------------------------------
# Main Valuation Function
# ---------------------------------------------------------------------------
def get_property_valuation(
    address, property_type, bedrooms, bathrooms, sq_ft,
    land_size, land_unit, covered_area,
    year_built_category, condition, stories, parking, pool, basement,
    photos
):
    print("\n\n--- RUNNING HOMELYTICS PK V15 ---")

    # --- Validation ---
    if not address or not address.strip():
        return "Please enter a property address.", "", "", ""
    if not photos:
        return "Please upload at least one property photo.", "", "", ""
    if property_type == "Plot":
        if not land_size or land_size <= 0:
            return "Please enter a valid Land Size greater than 0.", "", "", ""
    elif property_type not in ["Mall", "Warehouse"]:
        if not sq_ft or sq_ft <= 0:
            return "Please enter a valid Square Footage greater than 0.", "", "", ""

    # --- Geocoding ---
    geolocator = Nominatim(user_agent="homelytics_pk_v15", timeout=20)
    location = find_location_sequentially(geolocator, address)
    if not location:
        return "Could not find this location. Please try a more specific address (include area and city).", "", "", ""
    city = get_city_from_nominatim(location)
    if not city:
        return (
            "Location found but city not recognised. Supported cities: Lahore, Karachi, Islamabad, "
            "Rawalpindi, Faisalabad, Peshawar, Multan, Quetta, Sialkot, Gujranwala.", "", "", ""
        )
    loc_confidence, loc_confidence_note = get_location_confidence(location, address)
    formatted_address = location.address
    lat = location.latitude
    lng = location.longitude

    # --- Society detection ---
    society_name, society_premium = detect_society_premium(address)
    society_note = f"Society/premium area detected: {society_name} (+{int(society_premium*100)}% premium applied)" if society_name else "No premium society detected."

    # --- Unit conversions ---
    land_sqft = land_to_sqft_pk(land_size, land_unit) if property_type == "Plot" else 0
    effective_sqft = land_sqft if property_type == "Plot" else (sq_ft or 0)

    # --- Deterministic price estimate ---
    est_low, est_high, price_per_sqft = compute_deterministic_estimate(
        city, property_type, effective_sqft, land_sqft, condition, year_built_category, society_premium
    )

    # --- Market research (multi-query) ---
    print(f"INFO: Running market research for {city}...")
    market_research_results = multi_query_search(city, property_type, sq_ft, land_size, land_unit)
    low_data = len(market_research_results) < 300 or "No market data" in market_research_results
    low_data_warning = "\n\n> ⚠️ **Limited market data** — estimate based primarily on base rates. Verify with a local agent.\n\n" if low_data else ""

    # --- Parallel image analysis ---
    print("INFO: Analysing photos in parallel...")
    combined_image_analysis = analyze_images_parallel(photos)

    # --- Build property details ---
    extras = []
    if stories > 1:       extras.append(f"{stories} stories")
    if parking != "None": extras.append(f"Parking: {parking}")
    if pool:              extras.append("Swimming pool")
    if basement:          extras.append("Basement")
    extras_str = ", ".join(extras) if extras else "None specified"

    if property_type == "Plot":
        property_details_str = (
            f"- Address: {address}\n"
            f"- Geocoded: {formatted_address}\n"
            f"- Coordinates: {lat:.4f}, {lng:.4f}\n"
            f"- City: {city}\n"
            f"- Type: {property_type}\n"
            f"- Land Size: {land_size} {land_unit} ({round(land_sqft)} sq ft)\n"
            f"- Condition: {condition}\n"
            f"- {society_note}"
        )
    else:
        property_details_str = (
            f"- Address: {address}\n"
            f"- Geocoded: {formatted_address}\n"
            f"- Coordinates: {lat:.4f}, {lng:.4f}\n"
            f"- City: {city}\n"
            f"- Type: {property_type}\n"
            f"- Sq Ft (built-up): {sq_ft}\n"
        )
        if covered_area and covered_area > 0:
            property_details_str += f"- Covered Area: {covered_area} sq ft\n"
        if property_type not in ["Mall", "Warehouse"]:
            property_details_str += f"- Bedrooms: {bedrooms}\n- Bathrooms: {bathrooms}\n"
        property_details_str += (
            f"- Year Built Category: {year_built_category}\n"
            f"- Condition: {condition}\n"
            f"- Additional Features: {extras_str}\n"
            f"- {society_note}"
        )

    # --- Deterministic estimate block ---
    if est_low and est_high:
        usd_low  = round(est_low  / 278)
        usd_high = round(est_high / 278)
        det_block = (
            f"\n\n---\n## 📊 Model-Based Estimate (Deterministic)\n"
            f"- **Price Range:** PKR {format_pkr(est_low)} – PKR {format_pkr(est_high)}\n"
            f"- **USD Equivalent:** ${usd_low:,} – ${usd_high:,}\n"
            f"- **Price per Sq Ft:** PKR {format_pkr(price_per_sqft)}\n"
            f"- **Based on:** City base rates × condition ({condition}) × age ({year_built_category}) × society premium ({int(society_premium*100)}%)\n"
            f"- **Location Confidence:** {loc_confidence} — {loc_confidence_note}\n\n---\n"
        )
    else:
        det_block = ""

    # --- AI narrative prompt ---
    final_prompt = f"""You are 'Homelytics', an expert AI real estate valuator for the Pakistani property market.

A deterministic model has already calculated a numeric estimate. Your job is to provide NARRATIVE COMMENTARY ONLY — do not repeat or recalculate the numbers. Begin directly with '# Homelytics AI Commentary'.

**Property Details:**
{property_details_str}

**Deterministic Estimate Already Provided:** PKR {format_pkr(est_low) if est_low else 'N/A'} – PKR {format_pkr(est_high) if est_high else 'N/A'}

**Live Market Research:**
{market_research_results}

**Photo Analysis:**
{combined_image_analysis}

**Your commentary must cover these sections:**
1. **Market Context** — What is happening in {city} real estate right now based on the research data?
2. **Property Strengths** — What features from the photos and details add value?
3. **Risk Factors** — What could hurt the value or make this a risky buy?
4. **Confidence Explanation** — Why is confidence {loc_confidence}? What data was strong or weak?
5. **Buy/Sell Recommendation** — One clear paragraph: is this a good time to buy or sell this type of property in {city}?
6. **Data Sources Used** — List what data sources informed this analysis.
7. **Disclaimer** — This is an AI estimate. Verify with a licensed valuator (RERA registered) before any transaction.

Keep each section concise. Do not hallucinate price numbers — the numeric estimate is already shown above."""

    print("INFO: Generating AI commentary...")
    ai_response = VALUATION_MODEL.generate_content(final_prompt)

    # --- Log request ---
    log_request(address, property_type, city, est_low, est_high)

    # --- Assemble final output ---
    final_output = (
        f"## 📍 Location\n"
        f"**Geocoded Address:** {formatted_address}  \n"
        f"**City:** {city}  \n"
        f"**Coordinates:** {lat:.4f}, {lng:.4f}  \n"
        f"**Location Confidence:** {loc_confidence} — {loc_confidence_note}\n\n"
        + det_block
        + low_data_warning
        + ai_response.text
    )

    print("--- VALUATION COMPLETE ---")
    return final_output, combined_image_analysis, market_research_results, society_note

# ---------------------------------------------------------------------------
# UI Visibility
# ---------------------------------------------------------------------------
def update_visibility(property_type):
    is_commercial = property_type in ["Mall", "Warehouse"]
    is_plot       = property_type == "Plot"
    show_rooms    = not is_commercial and not is_plot
    show_sqft     = not is_plot
    show_land     = is_plot
    show_covered  = not is_commercial and not is_plot
    return (
        gr.Slider(visible=show_rooms),
        gr.Slider(visible=show_rooms),
        gr.Number(visible=show_sqft),
        gr.Number(visible=show_land),
        gr.Dropdown(visible=show_land),
        gr.Number(visible=show_covered),
    )

# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------
def submit_feedback(feedback_text):
    if not feedback_text or not feedback_text.strip():
        return "Please enter feedback before submitting."
    entry = {"timestamp": datetime.datetime.now().isoformat(), "feedback": feedback_text}
    _request_log.append({"type": "feedback", **entry})
    print(f"FEEDBACK: {json.dumps(entry)}")
    return "Thank you! Your feedback helps improve Homelytics."

# ---------------------------------------------------------------------------
# Gradio UI
# ---------------------------------------------------------------------------
with gr.Blocks(theme=gr.themes.Soft(), title="Homelytics Pakistan") as demo:
    gr.Markdown("# 🏡 Homelytics Pakistan — AI Real Estate Valuator")
    gr.Markdown("*Gemini 1.5 Flash · Live Market Research · Deterministic Price Model · Parallel Image Analysis*")

    with gr.Row():
        # --- Input Column ---
        with gr.Column(scale=1):
            address = gr.Textbox(
                label="Property Address",
                placeholder="e.g., House 5, DHA Phase 6, Lahore"
            )
            property_type = gr.Dropdown(
                label="Property Type",
                choices=["House", "Apartment", "Plot", "Farmhouse", "Mall", "Warehouse"],
                value="House"
            )

            with gr.Group():
                bedrooms     = gr.Slider(label="Bedrooms",  minimum=1, maximum=30, step=1, value=3,    visible=True)
                bathrooms    = gr.Slider(label="Bathrooms", minimum=1, maximum=30, step=1, value=2,    visible=True)
                sq_ft        = gr.Number(label="Built-up Area (Sq Ft)", value=2250,                    visible=True)
                covered_area = gr.Number(label="Covered Area (Sq Ft) — optional", value=0,             visible=True)
                land_size    = gr.Number(label="Land Size",  value=10,                                 visible=False)
                land_unit    = gr.Dropdown(label="Land Unit", choices=["Marla","Kanal"], value="Marla", visible=False)

            with gr.Group():
                year_built_category = gr.Dropdown(
                    label="Year Built",
                    choices=["Brand New (0-2 yrs)","Recent (3-10 yrs)","Established (11-20 yrs)","Old (20+ yrs)"],
                    value="Recent (3-10 yrs)"
                )
                condition = gr.Dropdown(
                    label="Property Condition",
                    choices=["Excellent","Good","Average","Needs Renovation"],
                    value="Good"
                )
                stories = gr.Slider(label="Number of Stories", minimum=1, maximum=10, step=1, value=1)
                parking = gr.Dropdown(
                    label="Parking",
                    choices=["None","1 Car","2 Cars","3+ Cars","Covered Parking"],
                    value="1 Car"
                )
                pool     = gr.Checkbox(label="Swimming Pool")
                basement = gr.Checkbox(label="Basement")

            photos = gr.File(
                file_count="multiple",
                file_types=["image"],
                label="Upload Property Photos (max 5 recommended)"
            )
            submit_btn = gr.Button("🔍 Get Valuation", variant="primary", size="lg")

        # --- Output Column ---
        with gr.Column(scale=2):
            valuation_output = gr.Markdown(label="Valuation Report")

            with gr.Accordion("📸 Photo Analysis Details", open=False):
                image_analysis_output = gr.Textbox(label="Image Analysis", lines=10, interactive=False)

            with gr.Accordion("📰 Market Research Data", open=False):
                market_research_output = gr.Textbox(label="Raw Market Data", lines=10, interactive=False)

            with gr.Accordion("🏘️ Society / Area Detection", open=False):
                society_output = gr.Textbox(label="Society Detection Result", lines=2, interactive=False)

            with gr.Accordion("💬 Feedback — Was this estimate accurate?", open=False):
                feedback_input = gr.Textbox(
                    label="Your feedback",
                    placeholder="e.g. Actual sale price was PKR 2.8 crore, estimate was close.",
                    lines=3
                )
                feedback_btn    = gr.Button("Submit Feedback")
                feedback_output = gr.Textbox(label="", interactive=False)

    # --- Wire up visibility ---
    property_type.change(
        fn=update_visibility,
        inputs=property_type,
        outputs=[bedrooms, bathrooms, sq_ft, land_size, land_unit, covered_area]
    )

    # --- Wire up submit ---
    submit_btn.click(
        fn=get_property_valuation,
        inputs=[
            address, property_type, bedrooms, bathrooms, sq_ft,
            land_size, land_unit, covered_area,
            year_built_category, condition, stories, parking, pool, basement,
            photos
        ],
        outputs=[valuation_output, image_analysis_output, market_research_output, society_output]
    )

    # --- Wire up feedback ---
    feedback_btn.click(
        fn=submit_feedback,
        inputs=[feedback_input],
        outputs=[feedback_output]
    )

if __name__ == "__main__":
    demo.launch(share=True)
