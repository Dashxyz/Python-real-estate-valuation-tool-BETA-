                      # This was made by Yahya Ahmad AKA, Dashxyz

# Homelytics US V3
# Improvements: parallel image analysis, global model instances, additional property inputs,
# unit converters (acres/sqft), ZIP code extraction, HOA flag, multi-query market research,
# deterministic price/sqft model, location confidence, structured output sections,
# request logging, user feedback, validation for land_size

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

# Global model instances — instantiated once at startup
VISION_MODEL    = genai.GenerativeModel('gemini-1.5-flash-latest')
VALUATION_MODEL = genai.GenerativeModel('gemini-1.5-flash-latest')

# In-memory cache and log
_search_cache = {}
_request_log  = []

# ---------------------------------------------------------------------------
# Unit Converters
# ---------------------------------------------------------------------------
def acres_to_sqft(acres): return acres * 43560.0
def sqft_to_acres(sqft):  return sqft / 43560.0

def land_to_sqft_us(size, unit):
    if unit == "Acres":  return acres_to_sqft(size)
    return size  # already sqft

# ---------------------------------------------------------------------------
# Base Price-Per-Sqft Model (USD) — deterministic fallback
# Tier 1 = high cost cities, Tier 2 = mid, Tier 3 = affordable
# ---------------------------------------------------------------------------
TIER_1_STATES = {"California","New York","Washington","Massachusetts","Hawaii","Colorado","Oregon"}
TIER_2_STATES = {"Texas","Florida","Illinois","Georgia","Arizona","Nevada","Virginia","New Jersey","Maryland"}

PRICE_SQFT_USD = {
    "Tier1": {"Single-Family Home":550,"Condo":600,"Townhouse":500,"Multi-Family Home":450,"Mall":300,"Warehouse":180},
    "Tier2": {"Single-Family Home":280,"Condo":300,"Townhouse":260,"Multi-Family Home":230,"Mall":180,"Warehouse":110},
    "Tier3": {"Single-Family Home":160,"Condo":170,"Townhouse":150,"Multi-Family Home":130,"Mall":120,"Warehouse":70},
}
LAND_PRICE_PER_ACRE_USD = {"Tier1": 200000, "Tier2": 80000, "Tier3": 35000}

CONDITION_MULTIPLIERS = {"Excellent":1.20,"Good":1.05,"Average":1.00,"Needs Renovation":0.80}
AGE_MULTIPLIERS = {
    "Brand New (0-2 yrs)":1.15,"Recent (3-10 yrs)":1.05,
    "Established (11-20 yrs)":0.95,"Old (20+ yrs)":0.85
}

def get_price_tier(state):
    if state in TIER_1_STATES: return "Tier1"
    if state in TIER_2_STATES: return "Tier2"
    return "Tier3"

def compute_deterministic_estimate_us(state, property_type, sq_ft, land_sqft, condition, year_built_category, hoa):
    try:
        tier = get_price_tier(state)
        multiplier = CONDITION_MULTIPLIERS.get(condition,1.0) * AGE_MULTIPLIERS.get(year_built_category,1.0)
        if property_type == "Land":
            price_per_acre = LAND_PRICE_PER_ACRE_USD.get(tier,50000)
            acres = sqft_to_acres(land_sqft)
            total = price_per_acre * acres * multiplier
            price_per_sqft = price_per_acre / 43560
        else:
            base = PRICE_SQFT_USD.get(tier,{}).get(property_type,200)
            total = base * sq_ft * multiplier
            price_per_sqft = base * multiplier
        low  = total * 0.88
        high = total * 1.12
        return round(low), round(high), round(price_per_sqft)
    except Exception as e:
        print(f"Deterministic estimate error: {e}")
        return None, None, None

# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
def search_market_prices_ddg(query, region='us-en'):
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

def multi_query_search_us(city, state, zip_code, property_type, sq_ft, land_size, land_unit):
    zip_str = f" {zip_code}" if zip_code else ""
    if property_type == "Land":
        queries = [
            f"land price per acre {city} {state}{zip_str} USA 2024 2025",
            f"vacant land sale {city} {state} recent",
        ]
    else:
        queries = [
            f"{property_type} price per sq ft {city} {state}{zip_str} 2024 2025 Zillow Redfin",
            f"median home price {city} {state} 2024 2025",
            f"real estate market trend {city} {state} 2024",
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
def get_location_details_us(location):
    if not location:
        return None, None, None
    if hasattr(location,'raw') and 'address' in location.raw:
        a = location.raw['address']
        city    = a.get('city') or a.get('town') or a.get('village')
        state   = a.get('state')
        zip_code = a.get('postcode')
        if city and state:
            print(f"INFO: {city}, {state} {zip_code or ''}")
            return city, state, zip_code
    if hasattr(location,'address'):
        parts = [p.strip() for p in location.address.split(',')]
        if len(parts) >= 4:
            country = parts[-1]
            state   = parts[-3]
            city    = parts[-4]
            if "united states" in country.lower():
                return city, state, None
    return None, None, None

def get_location_confidence_us(location, address):
    if not location:
        return "Low","Address could not be geocoded."
    raw = location.raw.get('address',{})
    has_street  = bool(raw.get('road') or raw.get('house_number'))
    has_zip     = bool(raw.get('postcode'))
    has_city    = bool(raw.get('city') or raw.get('town'))
    score = sum([has_street, has_zip, has_city])
    if score == 3: return "High",   "Street, ZIP, and city all confirmed."
    if score == 2: return "Medium", "City and ZIP confirmed; street-level precision may vary."
    return "Low","Only approximate location matched. Please verify the address."

def find_location_sequentially(geolocator, address):
    attempts = [address, ", ".join(address.split(',')[-2:]) if ',' in address else address]
    for i, attempt in enumerate(attempts, 1):
        print(f"GEOCODING (ATTEMPT {i}): '{attempt}'")
        try:
            loc = geolocator.geocode(attempt, country_codes="us", language='en')
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
        "Analyze this US property image. "
        "Describe: (1) overall condition (Excellent/Good/Average/Needs Renovation), "
        "(2) architectural style (Colonial, Ranch, Craftsman, Modern, Mediterranean, etc.), "
        "(3) finish quality and notable features (granite counters, hardwood floors, pool, garage, etc.), "
        "(4) any red flags or issues that would negatively affect appraised value."
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
def log_request(address, property_type, city, state, estimated_low, estimated_high):
    entry = {
        "timestamp":     datetime.datetime.now().isoformat(),
        "address":       address,
        "property_type": property_type,
        "city":          city,
        "state":         state,
        "est_low_usd":   estimated_low,
        "est_high_usd":  estimated_high,
    }
    _request_log.append(entry)
    print(f"LOG: {json.dumps(entry)}")

# ---------------------------------------------------------------------------
# Main Valuation Function
# ---------------------------------------------------------------------------
def get_property_valuation(
    address, property_type, bedrooms, bathrooms, sq_ft,
    land_size, land_unit, hoa, hoa_amount,
    year_built_category, condition, stories, parking, pool, basement,
    photos
):
    print("\n\n--- RUNNING HOMELYTICS US V3 ---")

    # --- Validation ---
    if not address or not address.strip():
        return "Please enter a property address.", "", "", ""
    if not photos:
        return "Please upload at least one property photo.", "", "", ""
    if property_type == "Land":
        if not land_size or land_size <= 0:
            return "Please enter a valid Land Size greater than 0.", "", "", ""
    elif property_type not in ["Mall","Warehouse"]:
        if not sq_ft or sq_ft <= 0:
            return "Please enter a valid Square Footage greater than 0.", "", "", ""

    # --- Geocoding ---
    geolocator = Nominatim(user_agent="homelytics_us_v3", timeout=20)
    location   = find_location_sequentially(geolocator, address)
    if not location:
        return "Could not find this location. Include street, city, and state for best results.", "", "", ""
    city, state, zip_code = get_location_details_us(location)
    if not city or not state:
        return "Location found but city/state could not be determined. Please include city and state in the address.", "", "", ""
    loc_confidence, loc_confidence_note = get_location_confidence_us(location, address)
    formatted_address = location.address
    lat = location.latitude
    lng = location.longitude
    tier = get_price_tier(state)

    # --- Unit conversions ---
    land_sqft    = land_to_sqft_us(land_size, land_unit) if property_type == "Land" else 0
    effective_sqft = land_sqft if property_type == "Land" else (sq_ft or 0)

    # --- Deterministic estimate ---
    est_low, est_high, price_per_sqft = compute_deterministic_estimate_us(
        state, property_type, effective_sqft, land_sqft, condition, year_built_category, hoa
    )

    # --- Multi-query market research ---
    print(f"INFO: Running market research for {city}, {state}...")
    market_research_results = multi_query_search_us(city, state, zip_code, property_type, sq_ft, land_size, land_unit)
    low_data = len(market_research_results) < 300 or "No market data" in market_research_results
    low_data_warning = "\n\n> ⚠️ **Limited market data** — estimate based primarily on base rates. Cross-check on Zillow or Redfin.\n\n" if low_data else ""

    # --- Parallel image analysis ---
    print("INFO: Analysing photos in parallel...")
    combined_image_analysis = analyze_images_parallel(photos)

    # --- Build property details ---
    extras = []
    if stories > 1:       extras.append(f"{stories} stories")
    if parking != "None": extras.append(f"Parking: {parking}")
    if pool:              extras.append("Swimming pool")
    if basement:          extras.append("Basement")
    if hoa:               extras.append(f"HOA: ${hoa_amount:,.0f}/month" if hoa_amount else "HOA: Yes")
    extras_str = ", ".join(extras) if extras else "None specified"

    if property_type == "Land":
        property_details_str = (
            f"- Address: {address}\n"
            f"- Geocoded: {formatted_address}\n"
            f"- Coordinates: {lat:.4f}, {lng:.4f}\n"
            f"- City: {city}, {state}{f' {zip_code}' if zip_code else ''}\n"
            f"- Price Tier: {tier} market\n"
            f"- Type: {property_type}\n"
            f"- Land Size: {land_size} {land_unit} ({round(land_sqft):,} sq ft)\n"
            f"- Condition: {condition}\n"
            f"- Year: {year_built_category}"
        )
    else:
        property_details_str = (
            f"- Address: {address}\n"
            f"- Geocoded: {formatted_address}\n"
            f"- Coordinates: {lat:.4f}, {lng:.4f}\n"
            f"- City: {city}, {state}{f' {zip_code}' if zip_code else ''}\n"
            f"- Price Tier: {tier} market\n"
            f"- Type: {property_type}\n"
            f"- Sq Ft: {sq_ft:,}\n"
        )
        if property_type not in ["Mall","Warehouse"]:
            property_details_str += f"- Bedrooms: {bedrooms}\n- Bathrooms: {bathrooms}\n"
        property_details_str += (
            f"- Year Built: {year_built_category}\n"
            f"- Condition: {condition}\n"
            f"- Additional Features: {extras_str}"
        )

    # --- Deterministic block ---
    if est_low and est_high:
        pkr_low  = round(est_low  * 278)
        pkr_high = round(est_high * 278)
        det_block = (
            f"\n\n---\n## 📊 Model-Based Estimate (Deterministic)\n"
            f"- **Price Range:** ${est_low:,} – ${est_high:,}\n"
            f"- **PKR Equivalent:** PKR {pkr_low:,} – PKR {pkr_high:,}\n"
            f"- **Price per Sq Ft:** ${price_per_sqft:,}\n"
            f"- **Market Tier:** {tier} ({state})\n"
            f"- **Based on:** State base rates × condition ({condition}) × age ({year_built_category})\n"
            f"- **Location Confidence:** {loc_confidence} — {loc_confidence_note}\n\n---\n"
        )
    else:
        det_block = ""

    # --- AI narrative prompt ---
    final_prompt = f"""You are 'Homelytics', an expert AI real estate valuator for the US property market.

A deterministic model has already calculated a numeric estimate. Your job is NARRATIVE COMMENTARY ONLY — do not repeat or recalculate the numbers. Begin directly with '# Homelytics AI Commentary'.

**Property Details:**
{property_details_str}

**Deterministic Estimate Already Provided:** ${est_low:,} – ${est_high:,}

**Live Market Research (Zillow, Redfin, etc.):**
{market_research_results}

**Photo Analysis:**
{combined_image_analysis}

**Your commentary must cover:**
1. **Market Context** — What is happening in {city}, {state} real estate right now?
2. **Property Strengths** — What features from the photos and details add value?
3. **Risk Factors** — What could hurt the value (HOA, condition, market slowdown, etc.)?
4. **School District & Neighborhood** — Comment on location quality based on what is known about {city}, {state}.
5. **Confidence Explanation** — Why is confidence {loc_confidence}? What data was strong or weak?
6. **Buy/Sell Recommendation** — One clear paragraph on current market conditions for this property type in {city}, {state}.
7. **Data Sources Used** — List what data sources informed this analysis.
8. **Disclaimer** — AI estimate only. Verify with a licensed appraiser (USPAP-certified) before any transaction.

Keep each section concise. Do not hallucinate price numbers."""

    print("INFO: Generating AI commentary...")
    ai_response = VALUATION_MODEL.generate_content(final_prompt)

    # --- Log request ---
    log_request(address, property_type, city, state, est_low, est_high)

    # --- Assemble final output ---
    zip_display = f" {zip_code}" if zip_code else ""
    final_output = (
        f"## 📍 Location\n"
        f"**Geocoded Address:** {formatted_address}  \n"
        f"**City/State/ZIP:** {city}, {state}{zip_display}  \n"
        f"**Coordinates:** {lat:.4f}, {lng:.4f}  \n"
        f"**Location Confidence:** {loc_confidence} — {loc_confidence_note}\n\n"
        + det_block
        + low_data_warning
        + ai_response.text
    )

    print("--- VALUATION COMPLETE ---")
    return final_output, combined_image_analysis, market_research_results, f"Price tier: {tier} market ({state})"

# ---------------------------------------------------------------------------
# UI Visibility
# ---------------------------------------------------------------------------
def update_visibility(property_type):
    is_commercial = property_type in ["Mall","Warehouse"]
    is_land       = property_type == "Land"
    show_rooms    = not is_commercial and not is_land
    show_sqft     = not is_land
    show_land     = is_land
    return (
        gr.Slider(visible=show_rooms),
        gr.Slider(visible=show_rooms),
        gr.Number(visible=show_sqft),
        gr.Number(visible=show_land),
        gr.Dropdown(visible=show_land),
    )

def update_hoa_amount(hoa):
    return gr.Number(visible=hoa)

# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------
def submit_feedback(feedback_text):
    if not feedback_text or not feedback_text.strip():
        return "Please enter feedback before submitting."
    entry = {"timestamp": datetime.datetime.now().isoformat(), "feedback": feedback_text}
    _request_log.append({"type":"feedback",**entry})
    print(f"FEEDBACK: {json.dumps(entry)}")
    return "Thank you! Your feedback helps improve Homelytics."

# ---------------------------------------------------------------------------
# Gradio UI
# ---------------------------------------------------------------------------
with gr.Blocks(theme=gr.themes.Soft(), title="Homelytics US") as demo:
    gr.Markdown("# 🇺🇸 Homelytics US — AI Real Estate Valuator")
    gr.Markdown("*Gemini 1.5 Flash · Live Market Research · Deterministic Price Model · Parallel Image Analysis*")

    with gr.Row():
        # --- Input Column ---
        with gr.Column(scale=1):
            address = gr.Textbox(
                label="Property Address",
                placeholder="e.g., 123 Main St, Beverly Hills, CA 90210"
            )
            property_type = gr.Dropdown(
                label="Property Type",
                choices=["Single-Family Home","Condo","Townhouse","Multi-Family Home","Land","Mall","Warehouse"],
                value="Single-Family Home"
            )

            with gr.Group():
                bedrooms  = gr.Slider(label="Bedrooms",  minimum=1, maximum=30, step=1, value=3, visible=True)
                bathrooms = gr.Slider(label="Bathrooms", minimum=1, maximum=30, step=1, value=2, visible=True)
                sq_ft     = gr.Number(label="Square Footage", value=2250,                         visible=True)
                land_size = gr.Number(label="Land Size",  value=1.0,                              visible=False)
                land_unit = gr.Dropdown(label="Land Unit", choices=["Acres","Sq Ft"], value="Acres", visible=False)

            with gr.Group():
                hoa        = gr.Checkbox(label="HOA (Homeowners Association)?")
                hoa_amount = gr.Number(label="HOA Monthly Fee ($)", value=0, visible=False)

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
                    choices=["None","1 Car Garage","2 Car Garage","3+ Car Garage","Street Parking"],
                    value="1 Car Garage"
                )
                pool     = gr.Checkbox(label="Swimming Pool")
                basement = gr.Checkbox(label="Basement / Finished Basement")

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

            with gr.Accordion("📊 Market Tier Info", open=False):
                tier_output = gr.Textbox(label="Price Tier", lines=1, interactive=False)

            with gr.Accordion("💬 Feedback — Was this estimate accurate?", open=False):
                feedback_input = gr.Textbox(
                    label="Your feedback",
                    placeholder="e.g. Actual sale price was $850k, estimate was close.",
                    lines=3
                )
                feedback_btn    = gr.Button("Submit Feedback")
                feedback_output = gr.Textbox(label="", interactive=False)

    # --- Wire up visibility ---
    property_type.change(
        fn=update_visibility,
        inputs=property_type,
        outputs=[bedrooms, bathrooms, sq_ft, land_size, land_unit]
    )
    hoa.change(fn=update_hoa_amount, inputs=hoa, outputs=hoa_amount)

    # --- Wire up submit ---
    submit_btn.click(
        fn=get_property_valuation,
        inputs=[
            address, property_type, bedrooms, bathrooms, sq_ft,
            land_size, land_unit, hoa, hoa_amount,
            year_built_category, condition, stories, parking, pool, basement,
            photos
        ],
        outputs=[valuation_output, image_analysis_output, market_research_output, tier_output]
    )

    # --- Wire up feedback ---
    feedback_btn.click(
        fn=submit_feedback,
        inputs=[feedback_input],
        outputs=[feedback_output]
    )

if __name__ == "__main__":
    demo.launch(share=True)
