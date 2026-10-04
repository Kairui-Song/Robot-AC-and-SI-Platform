"""Motor catalogue used by the read-only single-motor preflight UI.

Unknown EtherCAT identity and PDO data intentionally stay unset.  A profile
must never become motion-capable merely because its manufacturer was selected.
"""

MOTOR_PROFILES = {
    "johnson_r90_joint_a1": {
        "manufacturer": "德昌电机（Johnson Electric）",
        "model": "R-90/192-P-16 Joint-A1",
        "supply": "DC 24V（现场资料，待厂家手册复核）",
        "vendor_id": None,
        "product_code": None,
        "pdo_status": "待获取 ESI/实机扫描",
        "motion_allowed": False,
    },
    "eyou_servo_v144": {
        "manufacturer": "意优",
        "model": "EYOU ServoModule V144（现有平台记录）",
        "supply": "待补充",
        "vendor_id": 0x1097,
        "product_code": 0x2406,
        "pdo_status": "旧程序记录 0x1600/0x1A00，仍需实机复核",
        "motion_allowed": False,
    },
    "damiao_unconfirmed": {
        "manufacturer": "达妙",
        "model": "型号待选择",
        "supply": "待补充",
        "vendor_id": None,
        "product_code": None,
        "pdo_status": "待获取型号、ESI和实机扫描",
        "motion_allowed": False,
    },
    "te_unconfirmed": {
        "manufacturer": "泰科",
        "model": "型号待选择",
        "supply": "待补充",
        "vendor_id": None,
        "product_code": None,
        "pdo_status": "待获取型号、ESI和实机扫描",
        "motion_allowed": False,
    },
}


def public_profiles():
    return {key: dict(value) for key, value in MOTOR_PROFILES.items()}


def get_profile(profile_id):
    try:
        return dict(MOTOR_PROFILES[str(profile_id)])
    except KeyError as exc:
        raise ValueError("未知电机档案") from exc
