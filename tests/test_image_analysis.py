from unittest.mock import MagicMock, patch
from PIL import Image
from image_analysis import analyze_single_image, analyze_images_parallel, PROMPT_PK, PROMPT_US

def test_analyze_single_image():
    mock_model = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "Analysis result"
    mock_model.generate_content.return_value = mock_response

    img = Image.new("RGB", (10, 10))
    result = analyze_single_image(img, mock_model, PROMPT_PK)

    assert result == "Analysis result"
    mock_model.generate_content.assert_called_once_with([PROMPT_PK, img])

def test_analyze_images_parallel_empty():
    result = analyze_images_parallel([], MagicMock(), PROMPT_US)
    assert result == "No photos provided."

@patch("PIL.Image.open")
def test_analyze_images_parallel_success(mock_image_open):
    mock_img = Image.new("RGB", (10, 10))
    mock_image_open.return_value = mock_img

    mock_model = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "Good condition"
    mock_model.generate_content.return_value = mock_response

    fake_file1 = MagicMock()
    fake_file1.name = "img1.jpg"
    fake_file2 = MagicMock()
    fake_file2.name = "img2.jpg"

    result = analyze_images_parallel([fake_file1, fake_file2], mock_model, PROMPT_PK)

    assert "Good condition" in result
    assert result.count("Good condition") == 2
    assert mock_model.generate_content.call_count == 2

@patch("PIL.Image.open")
def test_analyze_images_parallel_exception(mock_image_open):
    mock_img = Image.new("RGB", (10, 10))
    mock_image_open.return_value = mock_img

    mock_model = MagicMock()
    mock_model.generate_content.side_effect = Exception("API error")

    fake_file = MagicMock()
    fake_file.name = "img.jpg"

    result = analyze_images_parallel([fake_file], mock_model, PROMPT_PK)

    assert "Image analysis failed: API error" in result
