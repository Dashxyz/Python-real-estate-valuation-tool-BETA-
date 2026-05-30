# Homelytics Pakistan V2.0 - Fixes: env var API key, sq_ft validation, marla/kanal input,
# confidence scoring, search cache, PKR/USD conversion, low data warning, placeholder comment removed

import google.generativeai as genai
import gradio as gr
from PIL import Image
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
from ddgs.ddgs import DDGS
import re
import time
import os

# --- Configuration ---
# FIX 1: API key now reads from environment variable instead of being hardcoded
# Set it in your terminal before running: export GOOGLE_AI_API_KEY="your-key-here"
# Or in Codespaces: add it to your repo secrets under Settings > Secrets
GOOGLE_AI_API_KEY = os.environ.get("GOOGLE_AI_API_KEY", "")
if not GOOGLE_AI_API_KEY:
    print("WARNING: GOOGLE_AI_API_KEY environment variable is not set. The app will not work.")
genai.configure(api_key=GOOGLE_AI_API_KEY)

# FIX 2: Simple in-memory cache for DuckDuckGo search results to avoid repeated hits
_search_cache = {}

# --- Helper Functions ---
def search_market_prices_ddg(query):
    # Return cached result if available
    if query in _search_cache:
        print(f"CACHE HIT: Returning cached results for '{query}'")
        return _search_cache[query]
    try:
        results = DDGS().text(query, region='pk-en', max_results=5)
        if not results:
            return "No recent market data found..."
        snippets = [
            f"Title: {item.get('title', 'N/A')}\nLink: {item.get('href', 'N/A')}\nSnippet: {item.get('body', 'N/A')}\n"
            for item in results
        ]
        result_text = "\n---\n".join(snippets)
        _search_cache[query] = result_text
        return result_text
    except Exception as e:
        print(f"DuckDuckGo Search Error: {e}")
        return "Could not perform market research due to an error."

def get_city_from_nominatim(location):
    if not location or not location.address:
        return None
    full_address = location.address.lower()
    address_parts = [part.strip() for part in full_address.split(',')]
    for part in address_parts:
        if 'lahore' in part: return 'Lahore'
        if 'karachi' in part: return 'Karachi'
        if 'islamabad' in part: return 'Islamabad'
        if 'rawalpindi' in part: return 'Rawalpindi'
        if 'faisalabad' in part: return 'Faisalabad'
        if 'peshawar' in part: return 'Peshawar'
    return None

# FIX 3: Removed leftover placeholder comment, function is now complete and clean
def find_location_sequentially(geolocator, address):
    print(f"GEOCODING (ATTEMPT 1): Trying exact address -> '{address}, Pakistan'")
    try:
        location = geolocator.geocode(f"{address}, Pakistan", country_codes="pk", language='en')
        if location:
            return location
        time.sleep(1)
    except (GeocoderTimedOut, GeocoderServiceError) as e:
        print(f"GEOCODING (ERROR on Attempt 1): {e}")

    match = re.search(
        r"((?:DHA|Bahria|Model|Gulberg|Johar)\s+(?:Town|City|Phase|Sector|Enclave)[\s\w\d-]+)",
        address, re.IGNORECASE
    )
    if match:
        general_area = match.group(1).strip()
        if "lahore" in address.lower():
            general_area += ", Lahore"
        elif "karachi" in address.lower():
            general_area += ", Karachi"
        elif "islamabad" in address.lower():
            general_area += ", Islamabad"
        print(f"GEOCODING (ATTEMPT 2): Trying general area -> '{general_area}, Pakistan'")
        try:
            location = geolocator.geocode(f"{general_area}, Pakistan", country_codes="pk", language='en')
            if location:
                return location
            time.sleep(1)
        except (GeocoderTimedOut, GeocoderServiceError) as e:
            print(f"GEOCODING (ERROR on Attempt 2): {e}")

    simplified_address = ", ".join(address.split(',')[-2:]) if ',' in address else " ".join(address.split()[-3:])
    print(f"GEOCODING (ATTEMPT 3): Trying simplified address -> '{simplified_address}, Pakistan'")
    try:
        location = geolocator.geocode(f"{simplified_address}, Pakistan", country_codes="pk", language='en')
        if location:
            return location
    except (GeocoderTimedOut, GeocoderServiceError) as e:
        print(f"GEOCODING (ERROR on Attempt 3): {e}")

    return None

# FIX 4: sq_ft validation + confidence scoring + PKR/USD conversion + low data warning
def get_property_valuation(address, property_type, bedrooms, bathrooms, sq_ft, land_size, land_unit, photos):
    print("\n\n--- RUNNING HOMELYTICS V14 ---")

    # Validation
    if property_type in ["Mall", "Warehouse"]:
        if not all([address, property_type, photos]):
            return "Please fill in Address, Property Type, and upload Photos.", "", ""
    elif property_type == "Plot":
        if not all([address, land_size, photos]):
            return "Please fill in Address, Land Size, and upload Photos.", "", ""
    elif not all([address, property_type, bedrooms, bathrooms, photos]):
        return "Please fill in all fields and upload at least one photo.", "", ""

    # FIX 5: sq_ft validation - must be a positive number
    if property_type not in ["Plot"] and (not sq_ft or sq_ft <= 0):
        return "Please enter a valid Square Footage (must be greater than 0).", "", ""

    try:
        geolocator = Nominatim(user_agent="homelytics_app_v14", timeout=20)
        location = find_location_sequentially(geolocator, address)
        if not location:
            return "Could not find this location. Please try a more specific address.", "", ""
        city = get_city_from_nominatim(location)
        if not city:
            return "Location found, but could not determine the city. Currently supported: Lahore, Karachi, Islamabad, Rawalpindi, Faisalabad, Peshawar.", "", ""

        print(f"INFO: City identified as '{city}'. Starting market research...")

        # Build search query based on property type
        if property_type == "Plot":
            search_query = f"current price per marla plot in {city} Pakistan 2024"
        else:
            search_query = f"current price of {sq_ft} sq ft {property_type} in {city} Pakistan 2024"

        market_research_results = search_market_prices_ddg(search_query)

        # FIX 6: Low data warning when search results are thin
        low_data_warning = ""
        if len(market_research_results) < 200 or "No recent market data" in market_research_results:
            low_data_warning = "\n\n> ⚠️ **Limited market data found** — this estimate may be less accurate than usual. Consider verifying with a local agent.\n\n"
            print("WARNING: Low market data detected.")

        print("INFO: Analyzing uploaded images with Gemini 1.5 Flash...")
        image_analysis_prompt = "Analyze this property image from Pakistan. Describe its condition (excellent/good/average/poor), architectural style, visible features, and any factors that would positively or negatively affect its market value."
        pil_images = [Image.open(photo.name) for photo in photos]
        vision_model = genai.GenerativeModel('gemini-1.5-flash-latest')
        image_descriptions = [vision_model.generate_content([image_analysis_prompt, img]).text for img in pil_images]
        combined_image_analysis = "\n".join(image_descriptions)

        print("INFO: Generating final valuation report...")
        valuation_model = genai.GenerativeModel('gemini-1.5-flash-latest')
        formatted_address = location.address

        # Build property details string
        if property_type == "Plot":
            property_details_str = (
                f"- User Address: {address}\n"
                f"- Found Location: {formatted_address}\n"
                f"- City: {city}\n"
                f"- Type: {property_type}\n"
                f"- Land Size: {land_size} {land_unit}"
            )
        else:
            property_details_str = (
                f"- User Address: {address}\n"
                f"- Found Location: {formatted_address}\n"
                f"- City: {city}\n"
                f"- Type: {property_type}\n"
                f"- Sq Ft: {sq_ft}"
            )
            if property_type not in ["Mall", "Warehouse"]:
                property_details_str += f"\n- Bedrooms: {bedrooms}\n- Bathrooms: {bathrooms}"

        # FIX 7: Prompt now requests confidence score and PKR/USD conversion
        final_prompt = f"""You are 'Homelytics', an expert AI real estate valuator for the Pakistani property market.

**Your task:** Provide a detailed property valuation report based on the data below.

**Property Details:**
{property_details_str}

**Live Market Research:**
{market_research_results}

**Photo Analysis:**
{combined_image_analysis}

**Your Valuation Report must include:**
1. **Estimated Market Value** in PKR (give a min-max range)
2. **USD Equivalent** (use approximate rate of 1 USD = 278 PKR)
3. **Confidence Level**: Rate your confidence as High, Medium, or Low, and explain why in one sentence
4. **Key Value Factors**: Bullet points of what is driving the value up or down
5. **Recommendation**: One paragraph on whether this is a good buy/sell at current market conditions
6. **Disclaimer**: Note that this is an AI estimate and should be verified with a licensed valuator

IMPORTANT: The property type is '{property_type}'. If Mall or Warehouse, treat as large commercial property. Do not mistake large sq ft values for typos."""

        final_response = valuation_model.generate_content(final_prompt)

        print("--- VALUATION COMPLETE ---")
        final_output = low_data_warning + final_response.text
        return final_output, combined_image_analysis, market_research_results

    except Exception as e:
        print(f"FULL ERROR: {e}")
        return f"An unexpected error occurred: {e}", "", ""


# --- UI Visibility Control ---
def update_visibility(property_type):
    is_commercial = property_type in ["Mall", "Warehouse"]
    is_plot = property_type == "Plot"
    show_rooms = not is_commercial and not is_plot
    show_sqft = not is_plot
    show_land = is_plot
    return (
        gr.Slider(visible=show_rooms),   # bedrooms
        gr.Slider(visible=show_rooms),   # bathrooms
        gr.Number(visible=show_sqft),    # sq_ft
        gr.Number(visible=show_land),    # land_size
        gr.Dropdown(visible=show_land),  # land_unit
    )


# --- Gradio UI ---
with gr.Blocks(theme=gr.themes.Soft(), title="Homelytics Pakistan") as demo:
    gr.Markdown("# 🏡 Homelytics Pakistan — AI Real Estate Valuator")
    gr.Markdown("*Powered by Gemini 1.5 Flash + Live Market Research*")

    with gr.Row():
        with gr.Column(scale=1):
            address = gr.Textbox(
                label="Property Address",
                placeholder="e.g., DHA Phase 6, Lahore or Packages Mall, Lahore"
            )
            property_type = gr.Dropdown(
                label="Property Type",
                choices=["House", "Apartment", "Plot", "Farmhouse", "Mall", "Warehouse"],
                value="House"
            )
            bedrooms = gr.Slider(label="Bedrooms", minimum=1, maximum=30, step=1, value=3, visible=True)
            bathrooms = gr.Slider(label="Bathrooms", minimum=1, maximum=30, step=1, value=2, visible=True)
            sq_ft = gr.Number(label="Square Footage (approx.)", value=2250, visible=True)

            # FIX 8: Land size inputs for plots (Marla/Kanal)
            land_size = gr.Number(label="Land Size", value=10, visible=False)
            land_unit = gr.Dropdown(
                label="Unit",
                choices=["Marla", "Kanal"],
                value="Marla",
                visible=False
            )

            photos = gr.File(
                file_count="multiple",
                file_types=["image"],
                label="Upload Property Photos"
            )
            submit_btn = gr.Button("Get Valuation", variant="primary")

        with gr.Column(scale=2):
            valuation_output = gr.Markdown(label="Valuation Report")
            with gr.Accordion("Show Technical Details", open=False):
                image_analysis_output = gr.Textbox(
                    label="Image Analysis Details", lines=10, interactive=False
                )
                market_research_output = gr.Textbox(
                    label="Live Market Research Snippets", lines=10, interactive=False
                )

    property_type.change(
        fn=update_visibility,
        inputs=property_type,
        outputs=[bedrooms, bathrooms, sq_ft, land_size, land_unit]
    )

    submit_btn.click(
        fn=get_property_valuation,
        inputs=[address, property_type, bedrooms, bathrooms, sq_ft, land_size, land_unit, photos],
        outputs=[valuation_output, image_analysis_output, market_research_output]
    )

if __name__ == "__main__":
    demo.launch(share=True)
