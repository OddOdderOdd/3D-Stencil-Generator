"""
core/quantizer.py
K-means color quantization via OpenCV.
"""

from __future__ import annotations
from dataclasses import dataclass

import cv2
import numpy as np

from config import KMEANS_MAX_ITER, KMEANS_EPSILON, KMEANS_ATTEMPTS


@dataclass
class QuantizeResult:
    label_map: np.ndarray        # shape (H, W), dtype int32 — cluster index per pixel
    centers_bgr: np.ndarray      # shape (N, 3), dtype uint8 — BGR color of each cluster
    quantized_image: np.ndarray  # shape (H, W, 3), dtype uint8 — reconstructed image
    n_colors: int


def quantize(image_bgr: np.ndarray, n_colors: int) -> QuantizeResult:
    """
    Reduce *image_bgr* to *n_colors* using K-means clustering.

    Parameters
    ----------
    image_bgr : np.ndarray
        Source image in BGR colour order (as loaded by cv2.imread).
    n_colors : int
        Number of clusters (colours) to reduce to.

    Returns
    -------
    QuantizeResult
        label_map       — integer cluster index for every pixel
        centers_bgr     — the cluster centroids in BGR order
        quantized_image — the image rebuilt from cluster centroids
    """
    if n_colors < 1:
        raise ValueError("n_colors must be >= 1")

    # K-means requires at least as many pixels as clusters, and OpenCV
    # requires the image to be at least 1 pixel in each dimension.
    # Upscale tiny images to a safe minimum size.
    MIN_DIM = max(n_colors * 2, 8)
    h, w = image_bgr.shape[:2]
    if h < MIN_DIM or w < MIN_DIM:
        new_h = max(h, MIN_DIM)
        new_w = max(w, MIN_DIM)
        image_bgr = cv2.resize(image_bgr, (new_w, new_h),
                               interpolation=cv2.INTER_NEAREST)
        h, w = image_bgr.shape[:2]

    pixels = image_bgr.reshape(-1, 3).astype(np.float32)

    # Clamp n_colors so it never exceeds the number of distinct pixels
    n_colors = min(n_colors, len(pixels))

    criteria = (
        cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER,
        KMEANS_MAX_ITER,
        KMEANS_EPSILON,
    )

    _, labels, centers = cv2.kmeans(
        pixels,
        n_colors,
        None,
        criteria,
        KMEANS_ATTEMPTS,
        cv2.KMEANS_PP_CENTERS,
    )

    centers = np.uint8(centers)
    labels_flat = labels.flatten()
    label_map = labels_flat.reshape(h, w).astype(np.int32)
    quantized = centers[labels_flat].reshape(h, w, 3)

    return QuantizeResult(
        label_map=label_map,
        centers_bgr=centers,
        quantized_image=quantized,
        n_colors=n_colors,
    )
