def get_result_class(status):
    """Return 'fg', 'ng', or None based on inspection status string."""
    status = str(status)
    if status in {"OBJECT PRESENT", "PASS", "PASS (OK)"}:
        return "fg"
    if status.startswith(("CLASSIFIED:", "CODE READ:", "PASSED:")):
        return "fg"
    if status in {"NO CODE", "NO TARGET"}:
        return "ng"
    if status.startswith("FAIL") or "DEFECT" in status:
        return "ng"
    return None
