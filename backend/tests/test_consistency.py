"""Quantity check on supported verdicts: same quantity, different value."""

from __future__ import annotations

from citecheck.support.consistency import number_conflicts, review_hint


def test_same_quantity_different_value():
    claim = "BN matches the accuracy with 140 times fewer training steps"
    ex = ("Batch Normalization achieves the same accuracy with 14 times "
          "fewer training steps, and beats the original model.")
    assert number_conflicts(claim, ex) == [("140 times", "14 times")]


def test_value_present_is_silent():
    assert number_conflicts("runs at 5 fps on a GPU",
                            "our system runs at 5 fps on a GPU") == []


def test_rounding_is_silent():
    assert number_conflicts("top-5 error of 3.57 % on the test set",
                            "top-5 error of 3.571 % on the test set") == []


def test_derived_difference_is_silent():
    # the claimed gain is the difference of two numbers the source states
    claim = "the model improves accuracy over the baseline by 0.42 % on MC500"
    ex = ("the baseline accuracy is 63.33 % on MC500 while our model "
          "accuracy reaches 63.75 % on MC500")
    assert number_conflicts(claim, ex) == []


def test_unrelated_context_is_silent():
    # the author's own result next to numbers about something else
    claim = "our net has fewer parameters yet reaches 6.43 % error"
    ex = "FitNet reaches 91.06 % accuracy on CIFAR-10 with maxout units"
    assert number_conflicts(claim, ex) == []


def test_cross_language_is_silent():
    assert number_conflicts("训练步数减少了 140 倍",
                            "with 14 times fewer training steps") == []


def test_chinese_same_quantity():
    claim = "该数据集包含 180 类目标，用于检测评测"
    ex = "该数据集包含 80 类目标，共 33 万张图像"
    assert number_conflicts(claim, ex) == [("180 类", "80 类")]


def test_review_hint_is_neutral():
    assert review_hint("runs at 5 fps", "runs at 5 fps") is None
    h = review_hint("BN needs 140 times fewer training steps",
                    "BN needs 14 times fewer training steps")
    assert "140 times" in h and "14 times" in h and "不支持" not in h
