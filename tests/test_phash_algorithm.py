"""
Tests for the pure-Python phash algorithm.

Validates that the DCT perceptual hash implementation produces:
- The correct output format (16-char lowercase hex)
- Stable results for the same input (determinism)
- Different results for different inputs
- Hashes within expected Hamming distance of themselves after minor transforms
"""

import sys
import os
import unittest
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers.phash_generator import _phash_from_sprite, _nfnt_resize_bilinear


def _make_sprite(r, g, b, width=160, height=90):
    """Create a solid-colour 5×5 sprite grid (25 frames) for testing."""
    frame = Image.new('RGB', (width, height), (r, g, b))
    sprite = Image.new('RGB', (width * 5, height * 5))
    for row in range(5):
        for col in range(5):
            sprite.paste(frame, (col * width, row * height))
    return sprite


def _make_gradient_sprite(horizontal=True, width=160, height=90):
    """Create a sprite with a strong gradient — has spatial frequency content for DCT."""
    arr = np.zeros((height * 5, width * 5, 3), dtype=np.uint8)
    if horizontal:
        for x in range(width * 5):
            arr[:, x, :] = int(x / (width * 5) * 255)
    else:
        for y in range(height * 5):
            arr[y, :, :] = int(y / (height * 5) * 255)
    return Image.fromarray(arr)


def _hamming(a, b):
    """Hamming distance between two 16-char hex strings."""
    ai = int(a, 16)
    bi = int(b, 16)
    return bin(ai ^ bi).count('1')


class TestPhashFormat(unittest.TestCase):
    def test_output_is_16_char_hex(self):
        sprite = _make_sprite(128, 64, 32)
        result = _phash_from_sprite(sprite)
        self.assertEqual(len(result), 16)
        self.assertTrue(all(c in '0123456789abcdef' for c in result))

    def test_output_is_lowercase(self):
        sprite = _make_sprite(200, 100, 50)
        result = _phash_from_sprite(sprite)
        self.assertEqual(result, result.lower())

    def test_not_all_zeros(self):
        sprite = _make_sprite(128, 64, 32)
        result = _phash_from_sprite(sprite)
        self.assertNotEqual(result, '0000000000000000')

    def test_not_all_ones(self):
        sprite = _make_sprite(128, 64, 32)
        result = _phash_from_sprite(sprite)
        self.assertNotEqual(result, 'ffffffffffffffff')


class TestPhashDeterminism(unittest.TestCase):
    def test_same_input_same_hash(self):
        sprite = _make_sprite(100, 150, 200)
        h1 = _phash_from_sprite(sprite)
        h2 = _phash_from_sprite(sprite)
        self.assertEqual(h1, h2)

    def test_different_gradients_different_hashes(self):
        # Solid colours have no spatial variation so DCT produces same hash.
        # Use gradients which have real spatial frequency content.
        h1 = _phash_from_sprite(_make_gradient_sprite(horizontal=True))
        h2 = _phash_from_sprite(_make_gradient_sprite(horizontal=False))
        self.assertNotEqual(h1, h2)

    def test_black_and_white_differ(self):
        h_black = _phash_from_sprite(_make_sprite(0, 0, 0))
        h_white = _phash_from_sprite(_make_sprite(255, 255, 255))
        self.assertNotEqual(h_black, h_white)


class TestPhashSimilarity(unittest.TestCase):
    def test_similar_colours_low_hamming(self):
        """Slightly different shades of the same colour should hash similarly."""
        h1 = _phash_from_sprite(_make_sprite(100, 100, 100))
        h2 = _phash_from_sprite(_make_sprite(105, 105, 105))
        dist = _hamming(h1, h2)
        self.assertLessEqual(dist, 10, f"Expected low Hamming distance, got {dist}")

    def test_opposite_gradients_high_hamming(self):
        """A left-to-right gradient vs its inverse should differ significantly."""
        arr_fwd = np.zeros((90 * 5, 160 * 5, 3), dtype=np.uint8)
        arr_rev = np.zeros((90 * 5, 160 * 5, 3), dtype=np.uint8)
        for x in range(160 * 5):
            v = int(x / (160 * 5) * 255)
            arr_fwd[:, x, :] = v
            arr_rev[:, x, :] = 255 - v
        h1 = _phash_from_sprite(Image.fromarray(arr_fwd))
        h2 = _phash_from_sprite(Image.fromarray(arr_rev))
        dist = _hamming(h1, h2)
        self.assertGreater(dist, 4, f"Expected significant Hamming distance, got {dist}")


class TestNfntResize(unittest.TestCase):
    def test_output_shape(self):
        img = Image.new('RGB', (160, 90), (128, 64, 32))
        result = _nfnt_resize_bilinear(img, 64, 64)
        self.assertEqual(result.shape, (64, 64, 3))

    def test_output_dtype(self):
        img = Image.new('RGB', (160, 90), (200, 100, 50))
        result = _nfnt_resize_bilinear(img, 64, 64)
        self.assertEqual(result.dtype, np.uint8)

    def test_pixel_range(self):
        img = Image.new('RGB', (160, 90), (255, 128, 0))
        result = _nfnt_resize_bilinear(img, 64, 64)
        self.assertGreaterEqual(result.min(), 0)
        self.assertLessEqual(result.max(), 255)

    def test_solid_colour_preserved(self):
        """A solid colour image should resize to the same solid colour."""
        img = Image.new('RGB', (160, 90), (100, 150, 200))
        result = _nfnt_resize_bilinear(img, 64, 64)
        # Allow ±2 for integer rounding
        self.assertTrue(np.all(np.abs(result[:, :, 0].astype(int) - 100) <= 2))
        self.assertTrue(np.all(np.abs(result[:, :, 1].astype(int) - 150) <= 2))
        self.assertTrue(np.all(np.abs(result[:, :, 2].astype(int) - 200) <= 2))


if __name__ == '__main__':
    unittest.main()
