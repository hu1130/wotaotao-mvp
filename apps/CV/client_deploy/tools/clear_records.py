"""一键清除: 打卡记录 / 人脸向量 / 员工信息"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import TENANT_ID
from core.tenant import normalize_tenant_id

TENANT_ID = normalize_tenant_id(TENANT_ID)


def main():
    print("=" * 50)
    print(f"  数据清除工具 (tenant={TENANT_ID})")
    print("=" * 50)
    print("  1. 清除所有打卡记录 (MySQL)")
    print("  2. 清除所有员工信息 (MySQL)")
    print("  3. 清除所有向量数据 (pgvector)")
    print("  4. 清除 Redis 签到/签退状态")
    print("  5. 清除全部 (MySQL + pgvector + Redis)")
    print("  0. 退出")
    print("=" * 50)
    print("  支持多选: 输入 1 2 或 1,2")

    raw = input("请选择: ").strip()
    if not raw:
        print("无效输入")
        return

    numbers = raw.replace(",", " ").split()
    for num in numbers:
        if num == "0":
            print("已退出")
            return
        elif num == "1":
            clear_attendance()
        elif num == "2":
            clear_employees()
        elif num == "3":
            clear_vectors()
        elif num == "4":
            clear_redis()
        elif num == "5":
            clear_attendance()
            clear_employees()
            clear_vectors()
            clear_redis()
        else:
            print(f"无效选项: {num}")


def clear_attendance():
    confirm = input("确认清除所有打卡记录? (y/n): ").strip().lower()
    if confirm != "y":
        print("已取消")
        return
    try:
        from core.attendance_db import AttendanceDB

        db = AttendanceDB()
        with db._connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM attendance WHERE tenant_id=%s", (TENANT_ID,))
        print(f"当前租户打卡记录已清除: {TENANT_ID}")
    except Exception as e:
        print(f"失败: {e}")


def clear_employees():
    confirm = input("确认清除所有员工信息? (y/n): ").strip().lower()
    if confirm != "y":
        print("已取消")
        return
    try:
        from core.attendance_db import AttendanceDB

        db = AttendanceDB()
        with db._connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM employees WHERE tenant_id=%s", (TENANT_ID,))
        print(f"当前租户员工信息已清除: {TENANT_ID}")
    except Exception as e:
        print(f"失败: {e}")


def clear_vectors():
    confirm = input("确认清除所有向量数据? (y/n): ").strip().lower()
    if confirm != "y":
        print("已取消")
        return
    try:
        from core.vector_db import VectorDB

        db = VectorDB()
        with db._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM face_embeddings WHERE tenant_id=%s", (TENANT_ID,)
                )
        print(f"当前租户向量数据已清除: {TENANT_ID}")
    except Exception as e:
        print(f"失败: {e}")


def clear_redis():
    confirm = input("确认清除所有 Redis 签到/签退状态? (y/n): ").strip().lower()
    if confirm != "y":
        print("已取消")
        return
    try:
        from core.redis_checkin import RedisCheckIn

        r = RedisCheckIn()
        if r._r is None:
            print("Redis 不可用, 无需清除")
            return
        deleted = 0
        for pattern in (
            f"checkin:{TENANT_ID}:*",
            f"checkout:{TENANT_ID}:*",
            f"checkin_cooldown:{TENANT_ID}:*",
        ):
            for key in r._r.scan_iter(match=pattern):
                r._r.delete(key)
                deleted += 1
        print(f"当前租户 Redis 清除完成: tenant={TENANT_ID} keys={deleted}")
    except Exception as e:
        print(f"失败: {e}")


if __name__ == "__main__":
    main()
