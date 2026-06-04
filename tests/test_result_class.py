import pytest
from core.result_class import get_result_class


class TestGetResultClass:
    # --- fg (good part) ---

    def test_object_present_is_fg(self):
        assert get_result_class("OBJECT PRESENT") == "fg"

    def test_pass_is_fg(self):
        assert get_result_class("PASS") == "fg"

    def test_pass_ok_is_fg(self):
        assert get_result_class("PASS (OK)") == "fg"

    def test_classified_with_count_is_fg(self):
        assert get_result_class("CLASSIFIED: 3") == "fg"

    def test_code_read_is_fg(self):
        assert get_result_class("CODE READ: ABC-123") == "fg"

    def test_passed_count_is_fg(self):
        assert get_result_class("PASSED: 5") == "fg"
        assert get_result_class("PASSED: 0") == "fg"

    # --- ng (bad part) ---

    def test_no_code_is_ng(self):
        assert get_result_class("NO CODE") == "ng"

    def test_no_target_is_ng(self):
        assert get_result_class("NO TARGET") == "ng"

    def test_fail_prefix_is_ng(self):
        assert get_result_class("FAIL = Sticker Missing") == "ng"
        assert get_result_class("FAIL = Sticker Upside-Down") == "ng"
        assert get_result_class("FAIL = Wrong Classification") == "ng"
        assert get_result_class("FAIL: something") == "ng"

    def test_defect_shape_is_ng(self):
        assert get_result_class("DEFECT SHAPE (NG)") == "ng"

    def test_defect_color_is_ng(self):
        assert get_result_class("DEFECT COLOR (NG)") == "ng"

    # --- None (unknown / neutral) ---

    def test_no_object_is_none(self):
        assert get_result_class("NO OBJECT") is None

    def test_no_template_is_none(self):
        assert get_result_class("NO TEMPLATE SET") is None

    def test_roi_changed_is_none(self):
        assert get_result_class("ROI SIZE CHANGED") is None

    def test_no_sticker_ref_is_none(self):
        assert get_result_class("NO STICKER REF") is None

    def test_empty_string_is_none(self):
        assert get_result_class("") is None

    def test_arbitrary_string_is_none(self):
        assert get_result_class("SOMETHING ELSE") is None

    # --- type coercion ---

    def test_none_input_coerced_to_string(self):
        # get_result_class converts to str → "None" → matches nothing → returns None
        assert get_result_class(None) is None

    def test_integer_input_coerced(self):
        assert get_result_class(0) is None
