# This is the Pakistani V13(BETA) of HOMELYTICS update:(SMART DYNAMIC UI + 1.5 FLASH for rate limits)
#   DISCLAIMER THIS CODE IS IN BETA AND IS NOT FULLY TESTED OR TRAINED 
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

# --- Helper Functions (No Changes Here) ---
def search_market_prices_ddg(query):
    try:
        results = DDGS().text(query, region='pk-en', max_results=5)
        if not results: return "No recent market data found..."
        snippets = [f"Title: {item.get('title', 'N/A')}\nLink: {item.get('href', 'N/A')}\nSnippet: {item.get('body', 'N/A')}\n" for item in results]
        return "\n---\n".join(snippets)
    except Exception as e:
        print(f"DuckDuckGo Search Error: {e}")
        return "Could not perform market research due to an error."

def get_city_from_nominatim(location):
    if not location or not location.address: return None
    full_address = location.address.lower()
    address_parts = [part.strip() for part in full_address.split(',')]
    for part in address_parts:
        if 'lahore' in part: return 'Lahore'
        if 'karachi' in part: return 'Karachi'
        if 'islamabad' in part: return 'Islamabad'
    return None

def find_location_sequentially(geolocator, address):
    print(f"GEOCODING (ATTEMPT 1): Trying exact address -> '{address}, Pakistan'")
    try:
        location = geolocator.geocode(f"{address}, Pakistan", country_codes="pk", language='en')
        if location: return location
        time.sleep(1)
    except (GeocoderTimedOut, GeocoderServiceError) as e: print(f"GEOCODING (ERROR on Attempt 1): {e}")
    match = re.search(r"((?:DHA|Bahria|Model|Gulberg|Johar)\s+(?:Town|City|Phase|Sector|Enclave)[\s\w\d-]+)", address, re.IGNORECASE)
    if match:
        general_area = match.group(1).strip()
        if "lahore" in address.lower(): general_area += ", Lahore"
        # (rest of function is the same)
        print(f"GEOCODING (ATTEMPT 2): Trying general area -> '{general_area}, Pakistan'")
        try:
            location = geolocator.geocode(f"{general_area}, Pakistan", country_codes="pk", language='en')
            if location: return location
            time.sleep(1)
        except (GeocoderTimedOut, GeocoderServiceError) as e: print(f"GEOCODING (ERROR on Attempt 2): {e}")
    simplified_address = ", ".join(address.split(',')[-2:]) if ',' in address else " ".join(address.split()[-3:])
    print(f"GEOCODING (ATTEMPT 3): Trying simplified address -> '{simplified_address}, Pakistan'")
    try:
        location = geolocator.geocode(f"{simplified_address}, Pakistan", country_codes="pk", language='en')
        if location: return location
    except (GeocoderTimedOut, GeocoderServiceError) as e: print(f"GEOCODING (ERROR on Attempt 3): {e}")
    return None

# --- Main Valuation Function (Small change to handle hidden sliders) ---
def get_property_valuation(address, property_type, bedrooms, bathrooms, sq_ft, photos):
    print("\n\n--- SUCCESS! RUNNING THE LATEST V13 (SMART DYNAMIC UI) CODE. ---")
    # Small change: If property type is Mall or Warehouse, bedrooms/bathrooms are not required
    if property_type in ["Mall", "Warehouse"]:
        if not all([address, property_type, sq_ft, photos]):
            return "Please fill in Address, Property Type, Sq Ft, and upload Photos.", "", ""
    elif not all([address, property_type, bedrooms, bathrooms, sq_ft, photos]):
        return "Please fill in all fields and upload at least one photo.", "", ""
    
    # (The rest of the function is the same as before)
    # ...
    try:
        geolocator = Nominatim(user_agent="homelytics_app_v13_final", timeout=20)
        location = find_location_sequentially(geolocator, address)
        if not location: return "Could not find this location...", "", ""
        city = get_city_from_nominatim(location)
        if not city: return "Location found, but could not determine the city...", "", ""

        print(f"INFO: City identified as '{city}'. Starting market research...")
        search_query = f"current price of a {sq_ft} sq ft {property_type} in {city} Pakistan"
        market_research_results = search_market_prices_ddg(search_query)
        
        print("INFO: Analyzing uploaded images with Gemini 1.5 Flash...")
        image_analysis_prompt = "Analyze the following image of a property in Pakistan. Describe its condition, style, and visible features relevant to its value."
        pil_images = [Image.open(photo.name) for photo in photos]
        vision_model = genai.GenerativeModel('gemini-1.5-flash-latest')
        image_descriptions = [vision_model.generate_content([image_analysis_prompt, img]).text for img in pil_images]
        combined_image_analysis = "\n".join(image_descriptions)
        
        print("INFO: Generating final valuation report...")
        valuation_model = genai.GenerativeModel('gemini-1.5-flash-latest')
        formatted_address = location.address

        # Constructing the property details string based on type
        property_details_str = f"- User Address: {address}\n- Found Location: {formatted_address}\n- City: {city}\n- Type: {property_type}\n- Sq Ft: {sq_ft}"
        if property_type not in ["Mall", "Warehouse", "Plot"]:
             property_details_str += f"\n- Bedrooms: {bedrooms}\n- Bathrooms: {bathrooms}"

        final_prompt = f"You are 'Homelytics', an expert AI real estate valuator for the Pakistani market. Provide a valuation in PKR. IMPORTANT: The user has specified the property type is a '{property_type}'. If this is a Mall or Warehouse, evaluate it as a large commercial property. Do not mistake a large Sq Ft value for a typo.\n\n**Market Research:**\n{market_research_results}\n\n**Property Details:**\n{property_details_str}\n\n**Photo Analysis:**\n{combined_image_analysis}\n\n**Valuation Report:**"
        final_response = valuation_model.generate_content(final_prompt)
        
        print("--- VALUATION COMPLETE ---")
        return final_response.text, combined_image_analysis, market_research_results
    except Exception as e:
        print(f"FULL ERROR: An unexpected error occurred: {e}")
        return f"An unexpected error occurred: {e}", "", ""

# --- NEW: Function to control UI element visibility ---
def update_visibility(property_type):
    """ Hides or shows sliders based on the selected property type. """
    if property_type in ["Mall", "Warehouse", "Plot"]:
        # If it's a commercial type or plot, hide the sliders
        return gr.Slider(visible=False), gr.Slider(visible=False)
    else:
        # For all other types (House, Apartment, etc.), show the sliders
        return gr.Slider(visible=True), gr.Slider(visible=True)

# --- Gradio UI ---
with gr.Blocks(theme=gr.themes.Soft(), title="Homelytics Pakistan") as demo:
    gr.Markdown("# 🏡 Homelytics Pakistan: AI Real Estate Valuator")
    with gr.Row():
        with gr.Column(scale=1):
            address = gr.Textbox(label="Property Address", placeholder="e.g., Packages Mall, Lahore")
            
            # --- CHANGE 1: Added "Mall" and "Warehouse" to the choices ---
            property_type = gr.Dropdown(
                label="Property Type", 
                choices=["House", "Apartment", "Plot", "Farmhouse", "Mall", "Warehouse"], 
                value="House"
            )
            
            # --- CHANGE 2: Increased the maximum for sliders to 30 ---
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
                
    # --- CHANGE 3: The "Magic". This line connects the dropdown to our visibility function ---
    property_type.change(
        fn=update_visibility, 
        inputs=property_type, 
        outputs=[bedrooms, bathrooms]
    )
    
    submit_btn.click(
        fn=get_property_valuation, 
        inputs=[address, property_type, bedrooms, bathrooms, sq_ft, photos], 
        outputs=[valuation_output, image_analysis_output, market_research_output]
    )

if __name__ == "__main__":
    demo.launch(share=True)