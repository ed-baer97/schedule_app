
import sys
import os
import logging
import time
from flask import Flask

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("reproduce_issue")

try:
    from app.services.schedule_solver import ClassSubjectRequirement
    from app.services.schedule_solver_hybrid import solve_schedule_hybrid
except ImportError as e:
    logger.error(f"Import error: {e}")
    sys.exit(1)

def run_test_scenario(name, requirements, settings, expected_success, expected_warnings=None, lesson_mode="pairs"):
    logger.info(f"\n{'='*20}\nSCENARIO: {name}\n{'='*20}")
    
    start = time.time()
    result = solve_schedule_hybrid(
        requirements=requirements,
        shift_id=1,
        existing_schedule={},
        schedule_settings=settings,
        clear_existing=True,
        time_limit_seconds=15,
        lesson_mode=lesson_mode
    )
    duration = time.time() - start
    
    suggestions = result.get('suggestions', [])
    warnings = result.get('warnings', [])
    summary = result.get('summary', '')
    
    logger.info(f"Duration: {duration:.2f}s")
    logger.info(f"Placed: {len(suggestions)}")
    logger.info(f"Warnings: {len(warnings)}")
    for w in warnings:
        logger.info(f"  WARN: {w}")
    
    total_hours = sum(r.total_hours_per_week for r in requirements)
    all_placed = len(suggestions) == total_hours
    
    if expected_success:
        if all_placed:
            logger.info("✅ SUCCESS: All lessons placed as expected.")
        else:
            logger.error(f"❌ FAILURE: Expected success, but placed {len(suggestions)}/{total_hours}")
    else:
        if not all_placed:
            logger.info("✅ SUCCESS: Not all lessons placed as expected (hard constraints).")
        else:
            logger.error("❌ FAILURE: Expected failure/partial placement, but ALL were placed (constraints ignored?).")

    return result


def get_teacher(tid, hours, cab):
    return {
        'teacher_id': tid, 
        'hours_per_week': hours, 
        'default_cabinet': cab, 
        'available_cabinets': [{'name': cab, 'priority': 1}], 
        'is_assigned_to_class': True
    }

def main():
    app = Flask(__name__)
    app.config['SQLALCHEMY_BINDS'] = {'school': 'sqlite:///:memory:'}
    
    with app.app_context():
        # Schedule settings: 5 days, 6 lessons
        settings_normal = {1: 6, 2: 6, 3: 6, 4: 6, 5: 6}
        
        # =================================================================================
        # SCENARIO 1: Teacher Conflict (Hard Constraint)
        # =================================================================================
        logger.info("--- SCENARIO 1: Teacher Conflict ---")
        settings_1day = {1: 6, 2: 0, 3: 0, 4: 0, 5: 0} # 6 slots total
        
        # Teacher 1 needs to teach 4 hours in 5A and 4 hours in 5B. Total 8 hours.
        # Available slots: 6.
        req_conflict = [
            ClassSubjectRequirement(1, 101, 4, False, [get_teacher(1, 4, '101')], "5A", "Math"),
            ClassSubjectRequirement(2, 101, 4, False, [get_teacher(1, 4, '101')], "5B", "Math"),
        ]
        
        res = run_test_scenario("Teacher Conflict", req_conflict, settings_1day, expected_success=False)
        # We expect exactly 6 lessons placed (max possible)
        placed = len(res.get('suggestions', []))
        if placed == 6:
            logger.info("✅ SUCCESS: Placed exactly 6 lessons (max capacity), 2 dropped.")
        else:
            logger.error(f"❌ FAILURE: Placed {placed} lessons (Expected 6)")

        
        # =================================================================================
        # SCENARIO 2: Cabinet Capacity 
        # =================================================================================
        logger.info("--- SCENARIO 2: Cabinet Capacity ---")
        # Cabinet 301 capacity defaults to 1 (since not in DB)
        # Teacher 3 (5A Physics) and Teacher 4 (5B Physics) both need Cabinet 301
        # 4 hours each = 8 hours total demand for Cabinet 301.
        # Slots: 6.
        
        req_cab_limit = [
            ClassSubjectRequirement(1, 103, 4, False, [get_teacher(3, 4, '301')], "5A", "Physics"),
            ClassSubjectRequirement(2, 103, 4, False, [get_teacher(4, 4, '301')], "5B", "Physics"),
        ]
        
        res = run_test_scenario("Cabinet Capacity", req_cab_limit, settings_1day, expected_success=False)
        placed = len(res.get('suggestions', []))
        if placed == 6:
            logger.info("✅ SUCCESS: Placed exactly 6 lessons (max cabinet capacity), 2 dropped.")
        else:
            logger.error(f"❌ FAILURE: Placed {placed} lessons (Expected 6)")
        
        
        # =================================================================================
        # SCENARIO 3: Window Minimization
        # =================================================================================
        logger.info("--- SCENARIO 3: Window Minimization ---")
        # 3 hours of Math in 6 slots. Should be contiguous (e.g. 1,2,3).
        req_windows = [
             ClassSubjectRequirement(1, 101, 3, False, [get_teacher(1, 3, '101')], "5A", "Math"),
        ]
        
        res_windows = run_test_scenario("Window Minimization", req_windows, settings_1day, expected_success=True)
        suggestions = res_windows.get('suggestions', [])
        lessons = sorted([s['lesson_number'] for s in suggestions])
        if lessons:
            gaps = 0
            for i in range(len(lessons)-1):
                if lessons[i+1] - lessons[i] > 1:
                    gaps += 1
            if gaps == 0:
                logger.info(f"✅ SUCCESS: No windows found (Lessons: {lessons})")
            else:
                logger.error(f"❌ FAILURE: Windows found! (Lessons: {lessons})")

        # =================================================================================
        # SCENARIO 4: "Pairs" Mode Check
        # =================================================================================
        logger.info("--- SCENARIO 4: Pairs Mode ---")
        # 4 hours of Math. Should form pairs (1-2, 3-4).
        req_pairs = [
             ClassSubjectRequirement(1, 101, 4, False, [get_teacher(1, 4, '101')], "5A", "Math"),
        ]
        
        res_pairs = run_test_scenario("Pairs Mode Check", req_pairs, settings_1day, expected_success=True, lesson_mode="pairs")
        suggestions = res_pairs.get('suggestions', [])
        lessons = sorted([s['lesson_number'] for s in suggestions])
        
        pairs_count = 0
        if 1 in lessons and 2 in lessons: pairs_count += 1
        if 3 in lessons and 4 in lessons: pairs_count += 1
        if 5 in lessons and 6 in lessons: pairs_count += 1
        
        if pairs_count >= 2:
             logger.info(f"✅ SUCCESS: Formed {pairs_count} pairs (Lessons: {lessons})")
        else:
             logger.warning(f"⚠️ WARNING: Pairs not optimal (Lessons: {lessons})")

        # =================================================================================
        # SCENARIO 5: Bad Data (Teacher Hours > Subject Hours)
        # =================================================================================
        logger.info("--- SCENARIO 5: Bad Data Check ---")
        # Subject requires 4 hours. Teacher has 30 hours assigned (typo in DB).
        # Solver MUST NOT place 30 lessons. It should cap at 4.
        
        req_bad_data = [
             ClassSubjectRequirement(1, 105, 4, False, [get_teacher(5, 30, '105')], "5A", "History"),
        ]
        
        # We expect SUCCESS (meaning it handled it gracefully), checking count internally
        res_bad = run_test_scenario("Bad Data (Hours > Limit)", req_bad_data, settings_1day, expected_success=True)
        suggestions = res_bad.get('suggestions', [])
        placed = len(suggestions)
        
        if placed == 4:
            logger.info(f"✅ SUCCESS: Automatically capped lessons at 4 (ignoring 30).")
        else:
            logger.error(f"❌ FAILURE: Placed {placed} lessons! (Expected 4). Algorithm exploded.")

        # =================================================================================
        # SCENARIO 6: Mixed Usage Exclusivity
        # =================================================================================
        logger.info("--- SCENARIO 6: Mixed Usage Exclusivity ---")
        # 5A Math (Whole Class) - 5 hours
        # 5A English (Subgroup) - 5 hours
        # Total 10 hours.
        # 1 Day (6 slots).
        # They CANNOT fit. Math needs 5 full slots. English needs 5 slots (even if half class).
        # Even if they try to share a slot (Math Taking Whole Class + English Taking Half), it should FAIL.
        # Math (Whole) blocks EVERYTHING else.
        
        req_mixed = [
             ClassSubjectRequirement(1, 101, 5, False, [get_teacher(1, 5, '101')], "5A", "Math"),
             ClassSubjectRequirement(1, 102, 5, True,  [get_teacher(2, 5, '102')], "5A", "English"),
        ]
        
        # We expect FAILURE (dropped lessons) because 5+5=10 > 6 slots.
        # If they share slots, we might see 6 slots used and 10 lessons placed (overlap).
        # We want strict usage: Max placed = 6 (or slightly less if optimizations fail). 
        # Ideally 6 lessons placed (e.g. 5 Math + 1 English, or mixed).
        
        res_mixed = run_test_scenario("Mixed Exclusivity", req_mixed, settings_1day, expected_success=False)
        suggestions = res_mixed.get('suggestions', [])
        placed = len(suggestions)
        
        if placed <= 6:
             logger.info(f"✅ SUCCESS: Placed {placed} lessons (<= 6). No illegal overlaps.")
        else:
             logger.error(f"❌ FAILURE: Placed {placed} lessons (> 6). Overlap detected!")





        # =================================================================================
        # SCENARIO 7: Subgroup Parallelism
        # =================================================================================
        logger.info("--- SCENARIO 7: Subgroup Parallelism ---")
        # Class 7A, Subject English (id 10), Total 4 hours (2 groups * 2 hours each)
        # 2 Teachers: T1 (Group 1), T2 (Group 2)
        # We want them to overlap as much as possible to save slots for the class.
        # Ideally, they should take 2 slots (Parallel).
        
        req_parallel = [
            ClassSubjectRequirement(7, 10, 2, True, [get_teacher(71, 2, '201')], "7A", "English (G1)"),
            ClassSubjectRequirement(7, 10, 2, True, [get_teacher(72, 2, '202')], "7A", "English (G2)"),
        ]
        
        res_parallel = run_test_scenario("Subgroup Parallelism", req_parallel, settings_1day, expected_success=True)
        suggestions = res_parallel.get('suggestions', [])
        slots_used = set(s['lesson_number'] for s in suggestions)
        
        if len(slots_used) == 2:
             logger.info(f"✅ SUCCESS: Subgroups are perfectly parallel (2 slots used for 4 tasks). Slots: {sorted(list(slots_used))}")
        else:
             logger.warning(f"⚠️ FAILURE: Subgroups scattered across {len(slots_used)} slots (Expected 2). Slots: {sorted(list(slots_used))}")

        # =================================================================================
        # SCENARIO 8: Max 2 Consecutive Lessons
        # =================================================================================
        logger.info("--- SCENARIO 8: Max 2 Consecutive Lessons ---")
        # Class 8A, Subject Math (id 20), 4 lessons.
        # Should NOT place 3 in a row.
        # Possible: 1,2, 4,5.
        # Forbidden: 1,2,3, 5.
        
        req_consecutive = [
             ClassSubjectRequirement(8, 20, 4, False, [get_teacher(81, 4, '301')], "8A", "Math"),
        ]
        
        # We need a longer day to see 3-in-a-row potential
        settings_long = {1: 8} 
        
        res_consecutive = run_test_scenario("Max 2 Consecutive", req_consecutive, settings_long, expected_success=True, lesson_mode='single')
        suggestions = res_consecutive.get('suggestions', [])
        slots_8 = sorted([s['lesson_number'] for s in suggestions])
        
        max_consecutive = 0
        current_consecutive = 1
        if slots_8:
            for i in range(1, len(slots_8)):
                if slots_8[i] == slots_8[i-1] + 1:
                    current_consecutive += 1
                else:
                    max_consecutive = max(max_consecutive, current_consecutive)
                    current_consecutive = 1
            max_consecutive = max(max_consecutive, current_consecutive)
        
        if max_consecutive <= 2:
            logger.info(f"✅ SUCCESS: Max consecutive is {max_consecutive}. Lessons: {slots_8}")
        else:
            logger.error(f"❌ FAILURE: Found sequence of {max_consecutive} (Expected <= 2). Lessons: {slots_8}")


if __name__ == '__main__':
    main()
