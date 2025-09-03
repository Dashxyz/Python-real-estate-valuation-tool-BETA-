# THIS IS THE US VERSION V1.2 of HOMELYTICS (with a stricter, more direct prompt)

import google.generativeai as genai
import gradio as gr
from PIL import Image
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
from ddgs.ddgs import DDGS 
import re
import time

# --- Configuration ---
GOOGLE_AI_API_KEY = ""
genai.configure(api_key=GOOGLE_AI_API_KEY)

# --- Helper Functions (No changes) ---
def search_market_prices_ddg(query):
    try:
        results = DDGS().text(query, region='us-en', max_results=5)
        if not results: return "No recent market data found..."
        snippets = [f"Title: {item.get('title', 'N/A')}\nLink: {item.get('href', 'N/A')}\nSnippet: {item.get('body', 'N/A')}\n" for item in results]
        return "\n---\n".join(snippets)
    except Exception as e:
        print(f"DuckDuckGo Search Error: {e}")
        return "Could not perform market research due to an error."

def get_location_details_us(location):
    if not location: return None, None
    if hasattr(location, 'raw') and 'address' in location.raw:
        address_data = location.raw['address']
        city = address_data.get('city') or address_data.get('town') or address_data.get('village')
        state = address_data.get('state')
        if city and state:
            print(f"INFO: Extracted City/State using structured data: {city}, {state}")
            return city, state
    if hasattr(location, 'address'):
        print("INFO: Could not find structured data, falling back to parsing address string.")
        parts = [p.strip() for p in location.address.split(',')]
        if len(parts) >= 4:
            country = parts[-1]
            state = parts[-3]
            city = parts[-4]
            if "united states" in country.lower() and (len(state) == 2 or len(state) > 4):
                 print(f"INFO: Extracted City/State using string parsing: {city}, {state}")
                 return city, state
    print("ERROR: Could not determine City and State from any method.")
    return None, None

def find_location_sequentially(geolocator, address):
    print(f"GEOCODING (ATTEMPT 1): Trying exact address -> '{address}, USA'")
    try:
        location = geolocator.geocode(f"{address}", country_codes="us", language='en')
        if location: return location
        time.sleep(1)
    except (GeocoderTimedOut, GeocoderServiceError) as e: print(f"GEOCODING (ERROR on Attempt 1): {e}")
    simplified_address = ", ".join(address.split(',')[-2:]) if ',' in address else address
    print(f"GEOCODING (ATTEMPT 2): Trying simplified address -> '{simplified_address}, USA'")
    try:
        location = geolocator.geocode(f"{simplified_address}", country_codes="us", language='en')
        if location: return location
    except (GeocoderTimedOut, GeocoderServiceError) as e: print(f"GEOCODING (ERROR on Attempt 2): {e}")
    return None

# --- Main Valuation Function ---
def get_property_valuation(address, property_type, bedrooms, bathrooms, sq_ft, photos):
    print("\n\n--- SUCCESS! RUNNING THE LATEST US VERSION (V1.2) CODE. ---")
    if property_type in ["Mall", "Warehouse", "Land"]:
        if not all([address, property_type, sq_ft, photos]):
            return "Please fill in Address, Property Type, Sq Ft, and upload Photos.", "", ""
    elif not all([address, property_type, bedrooms, bathrooms, sq_ft, photos]):
        return "Please fill in all fields and upload at least one photo.", "", ""
    
    try:
        geolocator = Nominatim(user_agent="homelytics_us_app_v1_2", timeout=20)
        location = find_location_sequentially(geolocator, address)
        if not location: return "Could not find this location...", "", ""
        
        city, state = get_location_details_us(location)
        if not city or not state: return "Location found, but could not determine the City and State.", "", ""

        print(f"INFO: Location identified as '{city}, {state}'. Starting market research...")
        search_query = f"current price of a {sq_ft} sq ft {property_type} in {city} {state}"
        market_research_results = search_market_prices_ddg(search_query)
        
        print("INFO: Analyzing uploaded images with Gemini 1.5 Flash...")
        image_analysis_prompt = "Analyze the following image of a property in the USA. Describe its condition, architectural style (e.g., Colonial, Modern, Ranch), and quality of finishes relevant to its value."
        pil_images = [Image.open(photo.name) for photo in photos]
        vision_model = genai.GenerativeModel('gemini-1.5-flash-latest')
        image_descriptions = [vision_model.generate_content([image_analysis_prompt, img]).text for img in pil_images]
        combined_image_analysis = "\n".join(image_descriptions)
        
        print("INFO: Generating final valuation report...")
        valuation_model = genai.GenerativeModel('gemini-1.5-flash-latest')
        formatted_address = location.address
        property_details_str = f"- User Address: {address}\n- Found Location: {formatted_address}\n- City: {city}\n- State: {state}\n- Type: {property_type}\n- Sq Ft: {sq_ft}"
        if property_type not in ["Mall", "Warehouse", "Land"]:
             property_details_str += f"\n- Bedrooms: {bedrooms}\n- Bathrooms: {bathrooms}"

        # --- CHANGE: Added a direct, forceful instruction block to the prompt ---
        final_prompt = f"You are 'Homelytics', an expert AI real estate valuator for the US market. Provide a valuation in USD. Consider US-specific factors like school districts and property taxes. IMPORTANT: The user has specified the property type is a '{property_type}'. Evaluate it accordingly and do not mistake a large Sq Ft value for a typo.\n\n**Market Research (from sources like Zillow, Redfin, etc.):**\n{market_research_results}\n\n**Property Details:**\n{property_details_str}\n\n**Photo Analysis:**\n{combined_image_analysis}\n\n**INSTRUCTIONS:** Your task is to provide a complete valuation report based ONLY on the data above. Do not introduce yourself or explain your capabilities. Begin your response directly with a markdown headline '# Homelytics Valuation Report'.\n\n**Valuation Report (in USD):**"
        
        final_response = valuation_model.generate_content(final_prompt)
        
        print("--- VALUATION COMPLETE ---")
        return final_response.text, combined_image_analysis, market_research_results
    except Exception as e:
        print(f"FULL ERROR: An unexpected error occurred: {e}")
        return f"An unexpected error occurred: {e}", "", ""

def update_visibility(property_type):
    """ Hides or shows sliders based on the selected property type. """
    if property_type in ["Mall", "Warehouse", "Land"]:
        return gr.Slider(visible=False), gr.Slider(visible=False)
    else:
        return gr.Slider(visible=True), gr.Slider(visible=True)

# --- Gradio UI (no changes) ---
with gr.Blocks(theme=gr.themes.Soft(), title="Homelytics US") as demo:
    gr.Markdown("# 🇺🇸 Homelytics US: AI Real Estate Valuator")
    with gr.Row():
        with gr.Column(scale=1):
            address = gr.Textbox(label="Property Address", placeholder="e.g., 101 Main St, Anytown, CA")
            property_type = gr.Dropdown(
                label="Property Type", 
                choices=["Single-Family Home", "Condo", "Townhouse", "Multi-Family Home", "Land", "Mall", "Warehouse"], 
                value="Single-Family Home"
            )
            bedrooms = gr.Slider(label="Bedrooms", minimum=1, maximum=30, step=1, value=3)
            bathrooms = gr.Slider(label="Bathrooms", minimum=1, maximum=30, step=1, value=2)
            sq_ft = gr.Number(label="Square Footage (approx.)", value=2250)
            photos = gr.File(file_count="multiple", file_types=["image"], label="Upload Property Photos")
            submit_btn = gr.Button("Get Valuation", variant="primary")
        with gr.Column(scale=2):
            valuation_output = gr.Markdown(label="Valuation Report")
            with gr.Accordion("Show Technical Details", open=False):
                image_analysis_output = gr.Textbox(label="Image Analysis Details", lines=10, interactive=False)
                market_research_output = gr.Textbox(label="Live Market Research Snippets", lines=10, interactive=False)
    property_type.change(fn=update_visibility, inputs=property_type, outputs=[bedrooms, bathrooms])
    submit_btn.click(fn=get_property_valuation, inputs=[address, property_type, bedrooms, bathrooms, sq_ft, photos], outputs=[valuation_output, image_analysis_output, market_research_output])

if __name__ == "__main__":
    demo.launch(share=True)