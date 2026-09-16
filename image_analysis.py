from PIL import Image
from concurrent.futures import ThreadPoolExecutor, as_completed

PROMPT_PK = (
    "Analyze this property image from Pakistan. "
    "Describe: (1) overall condition (Excellent/Good/Average/Needs Renovation), "
    "(2) architectural style and finish quality, "
    "(3) specific features visible (pool, garden, parking, extra floors, modern kitchen, etc.), "
    "(4) any red flags or issues that would negatively affect value."
)

PROMPT_US = (
    "Analyze this US property image. "
    "Describe: (1) overall condition (Excellent/Good/Average/Needs Renovation), "
    "(2) architectural style (Colonial, Ranch, Craftsman, Modern, Mediterranean, etc.), "
    "(3) finish quality and notable features (granite counters, hardwood floors, pool, garage, etc.), "
    "(4) any red flags or issues that would negatively affect appraised value."
)

def analyze_single_image(img, vision_model, prompt):
    return vision_model.generate_content([prompt, img]).text

def analyze_images_parallel(photos, vision_model, prompt, max_workers=4):
    if not photos:
        return "No photos provided."
    pil_images = [Image.open(p.name if hasattr(p, 'name') else p) for p in photos]
    descriptions = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(analyze_single_image, img, vision_model, prompt): i for i, img in enumerate(pil_images)}
        for future in as_completed(futures):
            try:
                descriptions.append(future.result())
            except Exception as e:
                descriptions.append(f"Image analysis failed: {e}")
    return "\n\n---\n\n".join(descriptions)
