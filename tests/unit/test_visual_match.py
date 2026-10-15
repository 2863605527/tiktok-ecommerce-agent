"""以图找货：视觉特征算法单测（纯本地，不联网）。"""
import io

from PIL import Image

from tiktok_ecommerce.image_processing.visual_match import (
    color_histogram,
    dominant_color,
    hamming,
    histogram_similarity,
    image_signature,
    phash,
    signature_similarity,
)


def _solid(rgb, size=(64, 64)):
    return Image.new("RGB", size, rgb)


def _quad(top_left, top_right, bottom_left, bottom_right):
    """2×2 色块图（有空间结构，模拟商品图案）。"""
    img = Image.new("RGB", (64, 64))
    px = img.load()
    for x in range(64):
        for y in range(64):
            if x < 32 and y < 32:
                px[x, y] = top_left
            elif x >= 32 and y < 32:
                px[x, y] = top_right
            elif x < 32:
                px[x, y] = bottom_left
            else:
                px[x, y] = bottom_right
    return img


def _noise(size=(64, 64)):
    import random
    random.seed(42)
    img = Image.new("RGB", size)
    px = img.load()
    for x in range(size[0]):
        for y in range(size[1]):
            px[x, y] = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
    return img


class TestPhash:
    def test_identical_images_same_hash(self):
        a = _solid((255, 0, 0))
        assert phash(a) == phash(a)

    def test_similar_images_close_hash(self):
        # 同结构图案的轻微亮度变化 → 汉明距离小
        a = _quad((200, 100, 50), (50, 200, 100), (100, 50, 200), (200, 200, 50))
        b = _quad((210, 105, 55), (55, 210, 105), (105, 55, 210), (210, 210, 55))
        assert hamming(phash(a), phash(b)) <= 16

    def test_different_structure_far_hash(self):
        # 结构不同（图案位置相反）→ 汉明距离大
        a = _quad((255, 0, 0), (0, 0, 255), (255, 255, 0), (0, 255, 0))
        b = _quad((0, 0, 255), (255, 0, 0), (0, 255, 0), (255, 255, 0))
        assert hamming(phash(a), phash(b)) > 16


class TestHistogram:
    def test_similarity_identical(self):
        h = color_histogram(_solid((120, 80, 40)))
        assert histogram_similarity(h, h) > 0.99

    def test_similarity_different_colors(self):
        h_red = color_histogram(_solid((255, 0, 0)))
        h_blue = color_histogram(_solid((0, 0, 255)))
        assert histogram_similarity(h_red, h_blue) < 0.3


class TestDominantColor:
    def test_red_detected(self):
        assert dominant_color(_solid((255, 0, 0))) in ("红/粉", "红紫")

    def test_gray_is_neutral(self):
        assert dominant_color(_solid((128, 128, 128))) == "中性色"


class TestSignatureSimilarity:
    def test_identical_signature(self):
        sig = image_signature(_solid((100, 100, 100)))
        assert signature_similarity(sig, sig) > 0.99

    def test_visual_similarity_high_same_product_variation(self):
        # 同款商品的不同亮度/轻微变体 → 综合相似度应明显高于完全不同商品
        a = image_signature(_solid((180, 120, 90)))
        b = image_signature(_solid((190, 125, 95)))
        c = image_signature(_solid((10, 200, 30)))
        assert signature_similarity(a, b) > signature_similarity(a, c)

    def test_pure_colors_separated_by_color_features(self):
        # pHash 对纯色无区分（无空间结构），颜色区分靠直方图+主色
        red = image_signature(_solid((255, 0, 0)))
        blue = image_signature(_solid((0, 0, 255)))
        assert signature_similarity(red, blue) < 0.6

    def test_range_bounds(self):
        a = image_signature(_noise())
        b = image_signature(_noise())
        s = signature_similarity(a, b)
        assert 0.0 <= s <= 1.0
