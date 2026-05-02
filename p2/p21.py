#!/usr/bin/env python3
# ============================================================
# Boost Cancellation Experiment (THREE COMMANDS)
#
#   1) generate : generate task sets -> JSONL
#   2) run      : run dynamic boost cancellation simulation -> boxplots + JSON
#   3) diff     : compare acceptance ratio (RMS vs Boosted-RM under boost_up budgets)
#                 and plot a line graph like your attachment.
#
# Acceptance rule used in `diff`:
#   - RMS accepts iff RMS RTA schedulable.
#   - Boosted-RM accepts iff:
#        (a) reduction feasible and reduced set is RMS-schedulable, and
#        (b) BoostUB <= boost_up * H
#     where BoostUB = sum_i floor(H/T_i) * w_i
#
# Requires: numpy, scipy, matplotlib
# ============================================================

import argparse
import json
import math
import random
from dataclasses import dataclass
from typing import List, Tuple, Dict, Optional, Any

import numpy as np
from scipy.stats import exponweib
import matplotlib.pyplot as plt

# ----------------------------
# Task model
# ----------------------------

@dataclass
class Task:
    T: int
    C: int

    @property
    def U(self) -> float:
        return self.C / self.T


# ----------------------------
# Utilities: LCM + hyperperiod
# ----------------------------

def lcm(a: int, b: int) -> int:
    return abs(a * b) // math.gcd(a, b)

def hyperperiod(tasks: List[Task], cap: int = 1_000_000) -> int:
    H = 1
    for t in tasks:
        H = lcm(H, t.T)
        if H > cap:
            # You can change this policy if you want, but keeping it deterministic avoids huge H
            # and makes experiments manageable.
            return cap
    return H

def hyperperiod_exact(tasks: List[Task], cap: int = 2_000_000) -> int:
    H = 1
    for t in tasks:
        H = lcm(H, t.T)
    return H


# ----------------------------
# UUniFast + period sampling
# ----------------------------

def uunifast(n: int, U_total: float, rng: random.Random) -> List[float]:
    utils = []
    sum_u = U_total
    for i in range(1, n):
        next_sum_u = sum_u * (rng.random() ** (1.0 / (n - i)))
        utils.append(sum_u - next_sum_u)
        sum_u = next_sum_u
    utils.append(sum_u)
    return utils

def log_uniform_int(low: int, high: int, rng: random.Random) -> int:
    x = math.exp(rng.uniform(math.log(low), math.log(high)))
    v = int(round(x))
    return max(low, min(high, v))

def generate_taskset(
        n: int,
        U_target: float,
        Tmin: int,
        Tmax: int,
        rng: random.Random,
        max_tries: int = 1_000_000,
        tol: float = 1e-6
) -> List[Task]:
    eps = 1e-12

    def total_u(ts):
        return sum(t.C / t.T for t in ts)

    def accept(U_actual: float) -> bool:
        if abs(U_target - 1.0) <= eps:
            return (1.0 - tol - eps) <= U_actual <= (1.0 + eps)
        else:
            return abs(U_actual - U_target) <= (tol + eps)

    def scale_taskset(tasks: list[Task], k: int) -> list[Task]:
        return [Task(T=t.T * k, C=t.C * k) for t in tasks]

    for _ in range(max_tries):
        utils = uunifast(n, U_target, rng)
        tasks: List[Task] = []

        # First n-1 tasks
        for ui in utils[:-1]:
            T = log_uniform_int(Tmin, Tmax, rng)
            C = int(round(ui * T))
            C = max(1, min(C, T))
            tasks.append(Task(T=T, C=C))

        U_so_far = total_u(tasks)
        remaining = U_target - U_so_far

        if remaining <= 0:
            continue

        # Choose Tn so that Cn can be at least 1
        min_Tn = max(Tmin, int(math.ceil(1.0 / (remaining + eps))))
        if min_Tn > Tmax:
            continue

        Tn = log_uniform_int(min_Tn, Tmax, rng)
        Cn_real = remaining * Tn

        if abs(U_target - 1.0) <= eps:
            Cn = int(math.floor(Cn_real + eps))  # never overshoot 1.0
        else:
            Cn = int(round(Cn_real))

        if not (1 <= Cn <= Tn):
            continue

        tasks.append(Task(T=Tn, C=Cn))
        tasks.sort(key=lambda x: x.T)

        U_final = total_u(tasks)
        if accept(U_final):
            tasks = scale_taskset(tasks, 1)
            return tasks

    raise RuntimeError("Could not generate a task set within tolerance; increase Tmax or tol.")


# ----------------------------
# RMS RTA
# ----------------------------

def rta_response_time(tasks_sorted_rm: List[Task], i: int, beta: float = 1.0) -> float:
    Ci = tasks_sorted_rm[i].C / beta
    Ti = tasks_sorted_rm[i].T
    R = Ci
    while True:
        interference = 0.0
        for j in range(i):
            interference += math.ceil(R / tasks_sorted_rm[j].T) * (tasks_sorted_rm[j].C / beta)
        Rn = Ci + interference
        if abs(Rn - R) < 1e-9:
            return R
        if Rn > Ti:
            return Rn
        R = Rn

def schedulable_rms_rta(tasks_sorted_rm: List[Task], beta: float = 1.0) -> bool:
    for i in range(len(tasks_sorted_rm)):
        if rta_response_time(tasks_sorted_rm, i, beta) > tasks_sorted_rm[i].T:
            return False
    return True


# ----------------------------
# Boosted-RM reduction -> w_i  (YOUR BACKTRACKING + RESET RULE)
# ----------------------------

import math
from typing import List, Tuple, Optional

# Assumes you already have:
#   - class/struct Task with fields: T, C
#   - schedulable_rms_rta(tasks: List[Task]) -> bool


def try_make_schedulable_with_reduction_straightforward(
        tasks_rm: List["Task"],
        sB: float
) -> Tuple[bool, List[int], List[int], List["Task"]]:
    """
    Straightforward baseline:
      Find Δ that makes the reduced task set schedulable AND minimizes BoostUB(H),
      where H is the hyperperiod.

    Returns: (ok, deltas, ws, reduced_tasks)
    """
    assert sB > 1.0

    tasks = sorted(tasks_rm, key=lambda x: x.T)
    n = len(tasks)
    extra = sB - 1.0

    # -------- hyperperiod H --------
    def lcm(a: int, b: int) -> int:
        return a // math.gcd(a, b) * b

    H = 1
    for tk in tasks:
        H = lcm(H, int(tk.T))

    # -------- helpers --------
    def w_from_delta(d: int) -> int:
        return 0 if d <= 0 else int(math.ceil(d / extra))

    def compute_ws(deltas_local: List[int]) -> List[int]:
        return [w_from_delta(d) for d in deltas_local]

    def apply_deltas(deltas_local: List[int]) -> List["Task"]:
        out = []
        for k, tk in enumerate(tasks):
            Cprime = tk.C - deltas_local[k]
            if Cprime < 0:
                Cprime = 0
            out.append(type(tk)(T=tk.T, C=Cprime))
        out.sort(key=lambda x: x.T)
        return out

    def boost_feasible(k: int, d: int) -> bool:
        """
        Lemma: sB * w <= C
        plus a conservative sanity check: w <= C' (optional but safe).
        """
        Ck = tasks[k].C
        wk = w_from_delta(d)
        Cprime = Ck - d
        return (sB * wk <= Ck) and (wk <= Cprime)

    # Δ_i^max = floor((sB-1)/sB * C_i)   (from your lemma)
    maxD = [int(math.floor((sB - 1.0) * tk.C / sB)) for tk in tasks]

    # BoostUB(H) = sum_{i} (H/T_i) * w_i   since H is multiple of T_i
    coeff = [H // int(tk.T) for tk in tasks]

    def boostub_H(deltas_local: List[int]) -> int:
        ws = compute_ws(deltas_local)
        return sum(coeff[i] * ws[i] for i in range(n))

    # -------- brute-force enumeration --------
    best_deltas: Optional[List[int]] = None
    best_ws: Optional[List[int]] = None
    best_reduced: Optional[List["Task"]] = None
    best_key: Optional[Tuple[int, int]] = None  # (BoostUB(H), sum(Δ))

    def dfs(i: int, deltas_cur: List[int]) -> None:
        nonlocal best_deltas, best_ws, best_reduced, best_key

        if i == n:
            reduced = apply_deltas(deltas_cur)
            if schedulable_rms_rta(reduced):
                ws = compute_ws(deltas_cur)
                cost = sum(coeff[j] * ws[j] for j in range(n))  # BoostUB(H)
                key = (cost, sum(deltas_cur))  # tie-breaker: smaller total reduction
                if best_key is None or key < best_key:
                    best_key = key
                    best_deltas = deltas_cur.copy()
                    best_ws = ws
                    best_reduced = reduced
            return

        # enumerate Δ_i in [0, maxD[i]]
        for d in range(0, maxD[i] + 1):
            if boost_feasible(i, d):
                deltas_cur.append(d)
                dfs(i + 1, deltas_cur)
                deltas_cur.pop()

    dfs(0, [])

    if best_deltas is None:
        deltas0 = [0] * n
        reduced0 = apply_deltas(deltas0)
        return False, deltas0, compute_ws(deltas0), reduced0

    return True, best_deltas, best_ws, best_reduced

def try_make_schedulable_with_reduction(tasks_rm: List[Task], sB: float) -> Tuple[bool, List[int], List[int], List[Task]]:
    assert sB > 1.0
    tasks = sorted(tasks_rm, key=lambda x: x.T)
    n = len(tasks)
    extra = sB - 1.0
    deltas = [0] * n

    def w_from_delta(d: int) -> int:
        return 0 if d <= 0 else int(math.ceil(d / extra))

    def compute_ws(deltas_local: List[int]) -> List[int]:
        return [w_from_delta(d) for d in deltas_local]

    def apply_deltas(deltas_local: List[int]) -> List[Task]:
        out = []
        for k, tk in enumerate(tasks):
            Cprime = tk.C - deltas_local[k]
            if Cprime < 0:
                Cprime = 0
            out.append(Task(T=tk.T, C=Cprime))
        out.sort(key=lambda x: x.T)
        return out

    def feasible_with_delta(k: int, d: int) -> bool:
        wk = w_from_delta(d)
        Cprime = tasks[k].C - d
        return wk <= Cprime

    def max_feasible_delta(k: int) -> int:
        """
        Largest d in [0, C_k-1] such that ceil(d/(sB-1)) <= C_k - d.
        (We keep C' >= 1 by capping at C_k-1.)
        """
        Ck = tasks[k].C
        hi = Ck - 1
        best = 0
        for d in range(0, hi + 1):
            if feasible_with_delta(k, d):
                best = d
        return best

    maxD = [max_feasible_delta(k) for k in range(n)]

    def feasible_idx(k: int) -> bool:
        return feasible_with_delta(k, deltas[k])

    def increment_and_fix_feasibility(start_idx: int) -> Optional[int]:
        """
        Increment Δ of tasks from start_idx down to 0, but NEVER beyond maxD[b].
        Returns index b incremented, or None if impossible.
        """
        b = start_idx
        while b >= 0:
            if deltas[b] >= maxD[b]:
                b -= 1
                continue
            deltas[b] += 1
            while b >= 0 and not feasible_idx(b):
                b -= 1
                if b < 0:
                    return None
                if deltas[b] >= maxD[b]:
                    continue
                deltas[b] += 1
            return b
        return None

    for i in range(n):
        while True:
            while True:
                reduced = apply_deltas(deltas)
                if schedulable_rms_rta(reduced[:i+1]):
                    break

                if deltas[i] >= maxD[i]:
                    if i == 0:
                        return False, deltas, compute_ws(deltas), reduced
                    b = increment_and_fix_feasibility(i - 1)
                    if b is None:
                        return False, deltas, compute_ws(deltas), reduced
                    for k in range(b + 1, i + 1):
                        deltas[k] = 0
                    continue

                deltas[i] += 1

            if feasible_idx(i):
                break

            if i == 0:
                return False, deltas, compute_ws(deltas), apply_deltas(deltas)

            b = increment_and_fix_feasibility(i - 1)
            if b is None:
                return False, deltas, compute_ws(deltas), apply_deltas(deltas)

            for k in range(b + 1, i + 1):
                deltas[k] = 0

    reduced_final = apply_deltas(deltas)
    ws_final = compute_ws(deltas)
    return True, deltas, ws_final, reduced_final


# ----------------------------
# Dynamic boost cancellation simulation (YOUR SLACK BROADCAST MODEL)
# ----------------------------

@dataclass
class Job:
    i: int
    deadline: int
    a_rem: float
    e_rem: float
    brem: int
    s_credit: float
    n_rem: float  # remaining normal-phase budget (C'_i)
    w_i: int


def pick_rm_job(ready: List[Job], tasks_rm: List[Task]) -> Optional[Job]:
    if not ready:
        return None
    return min(ready, key=lambda j: tasks_rm[j.i].T)


def sample_factor(rng: np.random.Generator, fmin: float, fmax: float, factor_cap: float = 5.0) -> float:
    scaling = rng.uniform(fmin, fmax)
    dist = exponweib(1, 1.044, loc=0, scale=1.0 / 0.214)
    s = dist.rvs(random_state=rng)
    return max(1.0, min(factor_cap, float(scaling * s)))

def actual_k_from_factor(C: int, factor: float) -> int:
    k = int(math.ceil(C / factor))
    return max(1, min(C, k))



def beta_min_global_closed_form(tasks: List[Task]) -> float:
    """
    Closed-form minimum global beta for your offline sufficient RTA bound.

    beta_i = (C_i + sum_{j<i} ceil(D_i/T_j) * C_j) / D_i
    beta_min = max_i beta_i

    Assumes implicit deadlines (D_i = T_i) and RM priority (increasing T).
    """
    tasks_rm = sorted(tasks, key=lambda x: x.T)

    beta = 1.0
    for i in range(len(tasks_rm)):
        Di = tasks_rm[i].T
        A = tasks_rm[i].C
        for j in range(i):
            A += math.ceil(Di / tasks_rm[j].T) * tasks_rm[j].C
        beta_i = A / float(Di)
        if beta_i > beta:
            beta = beta_i

    beta_l = 1.0
    beta_h = beta

    while beta_h - beta_l > 0.0005:
        print("beta_h = " + str(beta_h))
        new_beta = (beta_h + beta_l) / 2.0
        if schedulable_rms_rta(tasks, new_beta):
            beta_h = new_beta
        else:
            beta_l = new_beta

    return beta_h


def baseline_energy_global_scaling(H: int, W: int, beta: float, alpha_idle: float = 0.2) -> float:
    """
    Baseline energy over ONE hyperperiod for constant global scaling f = beta * f_n.

    Energy model (normalized):
      - Nominal energy per slot: E_N = 1
      - Idle energy per slot at frequency beta: E_I(beta) = alpha_idle * beta
      - Active energy per slot at frequency beta: E_A(beta) = beta^2

    Work model:
      - Total nominal workload over hyperperiod: W = sum (H/T_i) * C_i
      - With scaling beta, execution time becomes W/beta
      - Idle time = H - W/beta

    Returns E_base (total normalized energy over the hyperperiod).
    """
    busy = W / float(beta)
    idle = float(H) - busy
    if idle < 0.0:
        idle = 0.0

    E_busy = busy * (beta ** 2)              # active at beta
    E_idle = idle * (alpha_idle * beta)      # idle at beta
    return (E_busy + E_idle)/H


def simulate_one_horizon_dynamic_cancel(
        reduced_tasks: List[Task],
        tasks_rm: List[Task],
        w_per_task: List[int],
        sB: float,
        H: int,
        rng: np.random.Generator,
        fmin: float,
        fmax: float
) -> Tuple[bool, int, int, int, int, int, int]:
    """
    Returns: ok, boost_used_slots, boost_ub_slots_over_H, idle_slots_over_H, idle_lb_over_H
    Boost is only allowed AFTER the job has executed its reduced budget C'_i at nominal speed.
    """
    tasks = sorted(tasks_rm, key=lambda x: x.T)
    red   = sorted(reduced_tasks, key=lambda x: x.T)  # align by RM order

    ready: List[Job] = []
    boost_used = 0
    idle_slots = 0
    extra = sB - 1.0
    normal_used = 0

    boost_ub = sum((H // tasks[i].T) * w_per_task[i] for i in range(len(tasks)))
    idle_lb = H - sum((H // red[i].T) * red[i].C for i in range(len(red)))
    jobs_workload = 0
    for t in range(H):
        # releases
        for i, task in enumerate(tasks):
            if t % task.T == 0:
                factor = sample_factor(rng, fmin, fmax)
                k = actual_k_from_factor(task.C, factor)
                #print(k, task)
                #k = task.C
                jobs_workload += k
                Cp = red[i].C - w_per_task[i]   # reduced budget C'_i for this task (same period ordering)

                ready.append(Job(
                    i=i,
                    deadline=t + task.T,
                    a_rem=float(k),
                    e_rem=float(task.C),
                    brem=int(w_per_task[i]),
                    s_credit=0.0,
                    n_rem=float(Cp),   # must execute this much at nominal speed first
                    w_i=int(w_per_task[i])
                ))

        # deadline miss check
        for j in ready:
            if t >= j.deadline and j.a_rem > 1e-9:
                return False, boost_used, boost_ub, idle_slots, idle_lb, jobs_workload

        j = pick_rm_job(ready, tasks)
        if j is None:
            idle_slots += 1
            continue

        # -------------------------
        # EXECUTION RULE (FIXED):
        # Phase 1: normal until n_rem exhausted
        # Phase 2: boost-eligible; then cancellation/boost applies
        # -------------------------
        if j.a_rem <= 1e-9:
            ready.remove(j)
            continue

        if j.n_rem > 1e-12:
            # Not boost-eligible yet: forced nominal execution
            exec_amt = 1.0
            normal_used += 1
        else:
            # Boost-eligible region
            if j.brem > 0:
                if j.s_credit >= extra - 1e-12:
                    # cancel boost; consume replicated slack from all concurrent jobs with priority <= j
                    exec_amt = 1.0
                    normal_used += 1
                    for other in ready:
                        if other.i >= j.i:
                            other.s_credit = max(0.0, other.s_credit - extra)
                else:
                    # use boost
                    j.brem -= 1
                    boost_used += 1
                    exec_amt = sB
            else:
                print("here here here *****************************************************")
                boost_used += 1
                exec_amt = 1.0

        # execute: reduce actual remaining work and WCET budget
        j.a_rem -= exec_amt
        j.e_rem = max(0.0, j.e_rem - exec_amt)

        # also consume normal-phase budget at nominal rate only
        if j.n_rem > 1e-12:
            j.n_rem = max(0.0, j.n_rem - 1.0)

        # completion -> broadcast slack to all concurrent lower-priority jobs
        if j.a_rem <= 1e-9:
            if j.n_rem > 1e-12:
                slack = float(j.e_rem - extra*j.w_i)
            else:
                slack = float(j.e_rem/sB)
            if slack > 1e-12:
                for other in ready:
                    if other is not j and other.i > j.i:
                        other.s_credit += slack
            ready.remove(j)

    # end check
    for j in ready:
        if j.deadline <= H and j.a_rem > 1e-9:
            return False, boost_used, boost_ub, idle_slots, idle_lb, jobs_workload

    return True, boost_used, boost_ub, idle_slots, idle_lb, jobs_workload, normal_used


# def simulate_L_horizons_collect_samples(
#         reduced_task: List[Task],
#         tasks_rm: List[Task],
#         w_per_task: List[int],
#         sB: float,
#         H: int,
#         L: int,
#         seed: int,
#         fmin: float,
#         fmax: float
# ) -> Optional[Dict[str, Any]]:
#     """
#     Run L consecutive hyperperiods for ONE task set and return per-hyperperiod samples.
#     """
#     rng = np.random.default_rng(seed)
#
#     used_frac: List[float] = []
#     used_over_ub: List[float] = []
#     comp_ratio: List[float] = []
#     net_energy: List[float] = []
#     zero_boost_flags: List[int] = []
#
#     alpha = (sB ** 2) - 1.0  # (EB-EN)/EN
#     beta = 0.8              # (EN-EI)/EN, since EI=0.2EN
#
#     ub_slots_ref: Optional[int] = None
#
#     for _ in range(L):
#         ok, b_used, b_ub, n_idle, _idle_lb = simulate_one_horizon_dynamic_cancel(
#             reduced_task,
#             tasks_rm, w_per_task, sB, H, rng, fmin, fmax
#         )
#         if not ok:
#             return None
#
#         ub_slots_ref = b_ub
#         used_frac.append(float(b_used) / float(H))
#         used_over_ub.append((float(b_used) / float(b_ub)) if b_ub > 0 else 0.0)
#
#         if n_idle > 0:
#             comp_ratio.append( (alpha * float(b_used))/(beta * float(n_idle)))
#             zero_boost_flags.append(0)
#         else:
#             comp_ratio.append(float("nan"))
#             zero_boost_flags.append(1)
#
#         net_energy.append((float(b_used) * alpha - beta * float(n_idle)) / float(H))
#
#     return {
#         "ub_slots": float(ub_slots_ref if ub_slots_ref is not None else 0.0),
#         "samples_used_frac": used_frac,
#         "samples_used_over_ub": used_over_ub,
#         "samples_comp_ratio": comp_ratio,
#         "samples_net_energy": net_energy,
#         "samples_zero_boost": zero_boost_flags,
#     }

def boost_rm_energy_calc(H: int, n_normal: int, n_boost: int, n_idle: int, s_B: float, alpha_idle: float = 0.2) -> float:
    E_idle = n_idle * alpha_idle
    E_boost = n_boost * (s_B**2)
    E_normal = n_normal
    return  (E_idle + E_normal + E_boost)/H

def simulate_L_horizons_collect_samples(
        reduced_task: List[Task],
        tasks_rm: List[Task],
        w_per_task: List[int],
        sB: float,
        H: int,
        L: int,
        seed: int,
        fmin: float,
        fmax: float
) -> Optional[Dict[str, float]]:
    """
    Run L consecutive hyperperiods for ONE task set and
    return ONE aggregated sample (median over L).
    """
    rng = np.random.default_rng(seed)

    used_frac = []
    used_over_ub = []
    comp_ratio = []
    net_energy = []
    zero_boost_flags = []
    energy_ratio_to_global_freq = []

    alpha = (sB ** 2) - 1.0
    beta = 0.8

    ub_slots_ref: Optional[int] = None

    const_freq = beta_min_global_closed_form(tasks_rm)
    for _ in range(L):
        ok, b_used, b_ub, n_idle, _idle_lb, jobs_workload, normal_used = simulate_one_horizon_dynamic_cancel(
            reduced_task,
            tasks_rm, w_per_task, sB, H, rng, fmin, fmax
        )
        if not ok:
            return None

        ub_slots_ref = b_ub

        used_frac.append(b_used / H)
        used_over_ub.append((b_used / b_ub) if b_ub > 0 else 0.0)

        if b_used > 0:
            comp_ratio.append((beta * n_idle)/(alpha * b_used))
            zero_boost_flags.append(0)
        else:
            comp_ratio.append(float("nan"))
            zero_boost_flags.append(1)

        net_energy.append((b_used * alpha - beta * n_idle) / H)
        constant_freq_energy = baseline_energy_global_scaling(H, jobs_workload, const_freq)
        boost_rm_energy = boost_rm_energy_calc(H, normal_used, b_used, n_idle, sB)
        energy_ratio_to_global_freq.append(100*(constant_freq_energy-boost_rm_energy)/constant_freq_energy)

    # ---- aggregate over L ----
    return {
        "ub_slots": float(ub_slots_ref if ub_slots_ref else 0.0),
        "used_frac": float(np.nanmedian(used_frac)),
        "used_over_ub": float(np.nanmedian(used_over_ub)),
        "comp_ratio": float(np.nanmedian(comp_ratio)),
        "net_energy": float(np.nanmedian(net_energy)),
        "zero_boost": float(np.mean(zero_boost_flags)),
        "global_freq_improvement": float(np.nanmean(energy_ratio_to_global_freq)),
    }

# ----------------------------
# STEP A: Generate task sets to file (JSON Lines)
# ----------------------------

def generate_to_file(
        out_path: str,
        n: int,
        umin: int,
        umax: int,
        ustep: int,
        m: int,
        Tmin: int,
        Tmax: int,
        seed: int
) -> None:
    rng_py = random.Random(seed)
    U_list = [u / 100.0 for u in range(umin, umax + 1, ustep)]

    with open(out_path, "w", encoding="utf-8") as f:
        idx = 0
        for U in U_list:
            for _k in range(m):
                ts = generate_taskset(n, U, Tmin, Tmax, rng_py)
                ts_rm = sorted(ts, key=lambda x: x.T)
                rec = {
                    "id": idx,
                    "U_target": float(U),
                    "tasks": [{"T": t.T, "C": t.C} for t in ts_rm],
                }
                f.write(json.dumps(rec) + "\n")
                idx += 1

    print(f"[OK] Wrote {idx} task sets to {out_path}")


# ----------------------------
# STEP B: Run simulation from file
# ----------------------------

def q_ignore_nan(arr: List[float], p: float) -> float:
    if not arr:
        return 0.0
    a = np.asarray(arr, dtype=float)
    a = a[~np.isnan(a)]
    if a.size == 0:
        return 0.0
    return float(np.quantile(a, p))

def run_from_file(
        in_path: str,
        sb: float,
        Lruns: int,
        seed: int,
        fmin: float,
        fmax: float,
        out_png_time_box: str,
        out_png_ub_box: str,
        out_png_comp_box: str,
        out_png_net_box: str,
        out_png_global_freq_box: str,
        out_json: str
) -> None:
    # Load all task sets
    records: List[Dict[str, Any]] = []
    with open(in_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))

    if not records:
        raise RuntimeError("No task sets found in input file.")

    U_vals = sorted({float(r["U_target"]) for r in records})[-3:]
    by_U: Dict[float, List[Dict[str, Any]]] = {u: [] for u in U_vals}
    for r in records:
        if float(r["U_target"]) in U_vals:
            by_U[float(r["U_target"])].append(r)

    xs: List[float] = []
    box_time_data: List[List[float]] = []
    box_ub_data: List[List[float]] = []
    box_comp_data: List[List[float]] = []
    box_net_data: List[List[float]] = []
    box_energy_global_improvement: List[List[float]] = []

    summaries: List[Dict[str, float]] = []
    raw_samples_by_U: Dict[str, Dict[str, List[float]]] = {}

    for U in U_vals:
        xs.append(U)

        recs = by_U[U]
        m = len(recs)

        all_used_frac: List[float] = []
        all_used_over_ub: List[float] = []
        all_comp: List[float] = []
        all_net: List[float] = []
        all_zero_boost: List[int] = []
        all_global_freq_improvement: List[float] = []

        num_rms_sched = 0
        num_boost_needed = 0
        total_runs = 0
        scale_fac = 10
        for r in recs:
            tasks = [Task(T=int(t["T"])*scale_fac, C=int(t["C"])*scale_fac) for t in r["tasks"]]
            ts_rm = sorted(tasks, key=lambda x: x.T)

            print(tasks)
            # skip RMS-schedulable task sets
            if schedulable_rms_rta(ts_rm):
                num_rms_sched += 1
                continue

            feasible, _deltas, ws, reduced = try_make_schedulable_with_reduction(ts_rm, sb)
            if (not feasible) or (not schedulable_rms_rta(reduced)):
                continue

            exactH = hyperperiod_exact(ts_rm)
            boost_ub = sum((exactH // ts_rm[i].T) * ws[i] for i in range(len(ts_rm)))
            budget = 0.3 * float(exactH)
            if float(boost_ub) > budget :
                continue

            H = hyperperiod(ts_rm)
            print(H)
            rec_seed = seed + int(r["id"]) * 1337

            stats = simulate_L_horizons_collect_samples(
                reduced,
                ts_rm, ws, sb, H, Lruns,
                seed=rec_seed,
                fmin=fmin, fmax=fmax
            )
            if stats is None:
                continue

            num_boost_needed += 1
            total_runs += Lruns
            # all_used_frac.extend(stats["samples_used_frac"])
            # all_used_over_ub.extend(stats["samples_used_over_ub"])
            # all_comp.extend(stats["samples_comp_ratio"])
            # all_net.extend(stats["samples_net_energy"])
            # all_zero_boost.extend(stats["samples_zero_boost"])
            if stats["used_over_ub"] > 0.12:
                print("hi hi hi hi")
                print(tasks)
                print(feasible, _deltas, ws, reduced)
            all_used_frac.append(stats["used_frac"])
            all_used_over_ub.append(stats["used_over_ub"])
            all_comp.append(stats["comp_ratio"])
            all_net.append(stats["net_energy"])
            all_zero_boost.append(stats["zero_boost"])
            all_global_freq_improvement.append(stats["global_freq_improvement"])

        time_pct = [100.0 * x for x in all_used_frac]
        ub_pct = [100.0 * x for x in all_used_over_ub]
        print(all_comp)
        print(all_net)
        box_time_data.append(time_pct if time_pct else [0.0])
        box_ub_data.append(ub_pct if ub_pct else [0.0])
        box_comp_data.append(all_comp if all_comp else [float("nan")])
        box_net_data.append(all_net if all_net else [0.0])
        box_energy_global_improvement.append(all_global_freq_improvement if all_global_freq_improvement else [0.0])

        rms_sched_frac = float(num_rms_sched) / float(m) if m > 0 else 0.0
        zero_boost_rate = float(np.mean(all_zero_boost)) if all_zero_boost else 0.0

        summary = {
            "U": float(U),
            "generated_tasksets": float(m),
            "rms_sched_tasksets": float(num_rms_sched),
            "rms_sched_fraction": float(rms_sched_frac),
            "boost_needed_tasksets_used": float(num_boost_needed),
            "num_hyperperiod_runs": float(total_runs),

            "boost_used_time_pct_median": q_ignore_nan(time_pct, 0.50),
            "boost_used_time_pct_q1": q_ignore_nan(time_pct, 0.25),
            "boost_used_time_pct_q3": q_ignore_nan(time_pct, 0.75),

            "boost_used_over_ub_pct_median": q_ignore_nan(ub_pct, 0.50),
            "boost_used_over_ub_pct_q1": q_ignore_nan(ub_pct, 0.25),
            "boost_used_over_ub_pct_q3": q_ignore_nan(ub_pct, 0.75),

            "comp_ratio_median": q_ignore_nan(all_comp, 0.50),
            "comp_ratio_q1": q_ignore_nan(all_comp, 0.25),
            "comp_ratio_q3": q_ignore_nan(all_comp, 0.75),
            "zero_boost_rate": float(zero_boost_rate),

            "net_energy_per_slot_median": q_ignore_nan(all_net, 0.50),
            "net_energy_per_slot_q1": q_ignore_nan(all_net, 0.25),
            "net_energy_per_slot_q3": q_ignore_nan(all_net, 0.75),

            "global_freq_improvement_per_slot_median": q_ignore_nan(all_net, 0.50),
            "global_freq_improvement_per_slot_q1": q_ignore_nan(all_net, 0.25),
            "global_freq_improvement_per_slot_q3": q_ignore_nan(all_net, 0.75),
        }
        summaries.append(summary)

        raw_samples_by_U[f"{U:.2f}"] = {
            "boost_used_time_pct": time_pct,
            "boost_used_over_ub_pct": ub_pct,
            "comp_ratio": all_comp,
            "net_energy_per_slot": all_net,
            "zero_boost_flags": all_zero_boost,
            "global_freq_improvement_per_slot": all_global_freq_improvement,
        }

        print(
            f"U={U:.2f}  "
            f"RMS-sched={num_rms_sched}/{m} ({100.0*rms_sched_frac:.1f}%)  "
            f"Boost-needed-used={num_boost_needed}  "
            f"runs={total_runs:4d}  "
            f"median BoostUsedTime={summary['boost_used_time_pct_median']:.3f}%  "
            f"median BoostUsed/UB={summary['boost_used_over_ub_pct_median']:.3f}%  "
            f"median CompRatio={summary['comp_ratio_median']:.3f}  "
            f"zeroBoostRuns={100.0*zero_boost_rate:.1f}%  "
            f"median NetE={summary['net_energy_per_slot_median']:.4f}"
        )

    # ---- Plots ----
    # ---- Plots ----
    plt.figure()
    #plt.boxplot(box_time_data, showfliers=True)
    plt.violinplot(
        box_time_data[-3:],
        showmeans=True,
        showmedians=True,
        showextrema=True
    )
    plt.xticks(list(range(1, len(xs[-3:]) + 1)), [f"{u:.2f}" for u in xs[-3:]], fontsize=16)
    plt.xlabel("Utilization",  fontsize=18)
    plt.ylabel("Boost-Time Percentage", fontsize=18)
    plt.yticks(fontsize=16)
    plt.grid(True, linewidth=0.5)
    plt.tight_layout()
    plt.savefig(out_png_time_box, dpi=200)
    print(f"[OK] Saved figure: {out_png_time_box}")

    plt.figure()
    #plt.boxplot(box_ub_data, showfliers=True)
    plt.violinplot(
        box_ub_data[-3:],
        showmeans=True,
        showmedians=True,
        showextrema=True
    )
    plt.xticks(list(range(1, len(xs[-3:]) + 1)), [f"{u:.2f}" for u in xs[-3:]], fontsize=16)
    plt.xlabel("Utilization", fontsize=18)
    plt.ylabel("Boost Utilization (%)", fontsize=18)
    plt.yticks(fontsize=16)
    plt.grid(True, linewidth=0.5)
    plt.tight_layout()
    plt.savefig(out_png_ub_box, dpi=200)
    print(f"[OK] Saved figure: {out_png_ub_box}")

    plt.figure()
    #plt.boxplot(box_comp_data, showfliers=True)
    plt.violinplot(
        box_comp_data[-3:],
        showmeans=True,
        showmedians=True,
        showextrema=True
    )
    plt.xticks(list(range(1, len(xs[-3:]) + 1)), [f"{u:.2f}" for u in xs[-3:]], fontsize=16)
    plt.xlabel("Utilization", fontsize=18)
    plt.ylabel("Compensation Ratio", fontsize=18)
    plt.yticks(fontsize=16)
    plt.grid(True, linewidth=0.5)
    plt.tight_layout()
    plt.savefig(out_png_comp_box, dpi=200)
    print(f"[OK] Saved figure: {out_png_comp_box}")

    plt.figure()
    #plt.boxplot(box_net_data, showfliers=True)
    plt.violinplot(
        box_net_data[-3:],
        showmeans=True,
        showmedians=True,
        showextrema=True
    )
    plt.xticks(list(range(1, len(xs[-3:]) + 1)), [f"{u:.2f}" for u in xs[-3:]], fontsize=16)
    plt.xlabel("Utilization", fontsize=18)
    plt.ylabel("Net Energy per Slot", fontsize=18)
    plt.yticks(fontsize=16)
    plt.grid(True, linewidth=0.5)
    plt.tight_layout()
    plt.savefig(out_png_net_box, dpi=200)
    print(f"[OK] Saved figure: {out_png_net_box}")

    plt.figure()
    #plt.boxplot(box_net_data, showfliers=True)
    plt.violinplot(
        box_energy_global_improvement[-3:],
        showmeans=True,
        showmedians=True,
        showextrema=True
    )
    plt.xticks(list(range(1, len(xs[-3:]) + 1)), [f"{u:.2f}" for u in xs[-3:]], fontsize=16)
    plt.xlabel("Utilization", fontsize=18)
    plt.ylabel("Dynamic Energy Improvement", fontsize=18)
    plt.yticks(fontsize=16)
    plt.grid(True, linewidth=0.5)
    plt.tight_layout()
    plt.savefig(out_png_global_freq_box, dpi=200)
    print(f"[OK] Saved figure: {out_png_global_freq_box}")

    out = {
        "params": {
            "input_tasksets_file": in_path,
            "sB": sb,
            "L": Lruns,
            "seed": seed,
            "exec_model": {"fmin": fmin, "fmax": fmax},
            "energy_model": {
                "EN": 1.0,
                "EI": 0.2,
                "EB": "sB^2",
                "beta": 0.8,
                "alpha": "sB^2 - 1"
            },
            "note": "Metrics computed only over task sets NOT schedulable by RMS."
        },
        "series": {
            "U": xs,
            "summaries": summaries
        },
        "raw_samples_by_U": raw_samples_by_U
    }

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)

    print(f"[OK] Saved data: {out_json}")



# ----------------------------
# STEP C: diff (Acceptance Ratio Plot)
# ----------------------------
# ---- Reduction-structure stats at U = 1.0 only ----

def diff_from_file(
        in_path: str,
        sb: float,
        boost_up_list: List[float],   # e.g., [0.05, 0.10, 0.20, 0.30]
        out_png: str
) -> None:
    records: List[Dict[str, Any]] = []
    with open(in_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    if not records:
        raise RuntimeError("No task sets found in input file.")

    U_vals = sorted({float(r["U_target"]) for r in records})
    by_U: Dict[float, List[Dict[str, Any]]] = {u: [] for u in U_vals}
    for r in records:
        by_U[float(r["U_target"])].append(r)

    rms_accept: List[float] = []
    boosted_accept: Dict[float, List[float]] = {b: [] for b in boost_up_list}

    # ---- Reduction-structure stats at U = 1.0 only ----
    red_stats = {
        b: {
            "k_nonzero": [],        # number of tasks with Δ_i > 0
            "red_rate": [],         # (sum Δ_i/T_i) / Uall
            "bottom25_share": [],   # share of total Δ in lowest-priority quartile
            "bottom50_share": [],   # share of total Δ in lowest-priority half
        }
        for b in boost_up_list
    }

    for U in U_vals:
        recs = by_U[U]
        m = len(recs)
        if m == 0:
            rms_accept.append(0.0)
            for b in boost_up_list:
                boosted_accept[b].append(0.0)
            continue

        rms_ok = 0
        boosted_ok_count = {b: 0 for b in boost_up_list}

        for r in recs:
            tasks = [Task(T=int(t["T"])*10, C=int(t["C"])*10) for t in r["tasks"]]
            ts_rm = sorted(tasks, key=lambda x: x.T)

            H = hyperperiod_exact(ts_rm)

            rm_only = False
            # RMS acceptance
            if schedulable_rms_rta(ts_rm):
                if U == 1.0:
                    print(ts_rm)
                rms_ok += 1
                for b in boost_up_list:
                    boosted_ok_count[b] += 1
                continue

            # Boosted-RM acceptance under budgets
            feasible, _deltas, ws, reduced = try_make_schedulable_with_reduction(ts_rm, sb)
            if (not feasible) or (not schedulable_rms_rta(reduced)):
                continue

                # ---- compute reduction-structure features for this task set ----
            # tasks are RM-sorted already (ts_rm). Lowest priority = largest period = highest index.
            Uall = sum(t.C / t.T for t in ts_rm)
            if Uall <= 0:
                continue

            sum_red_over_T = sum((_deltas[i] / ts_rm[i].T) for i in range(len(ts_rm)))
            red_rate = sum_red_over_T / Uall  # normalized reduction rate

            k_nonzero = sum(1 for d in _deltas if d > 0)

            # concentration toward low-priority:
            n = len(ts_rm)
            if n > 0:
                q25 = max(1, int(math.ceil(0.25 * n)))
                q50 = max(1, int(math.ceil(0.50 * n)))

                total_delta = sum(_deltas)
                if total_delta > 0:
                    bottom25 = sum(_deltas[n - q25 : n])
                    bottom50 = sum(_deltas[n - q50 : n])
                    bottom25_share = bottom25 / total_delta
                    bottom50_share = bottom50 / total_delta
                else:
                    bottom25_share = 0.0
                    bottom50_share = 0.0
            else:
                bottom25_share = 0.0
                bottom50_share = 0.0


            boost_ub = sum((H // ts_rm[i].T) * ws[i] for i in range(len(ts_rm)))
            print(H, ts_rm, _deltas, ws, boost_ub)
            for b in boost_up_list:
                budget = float(b) * float(H)
                if float(boost_ub) <= budget + 1e-12:
                    boosted_ok_count[b] += 1
                    # ---- record paragraph stats only at U = 1.0 ----
                    if abs(U - 1.0) < 1e-12:
                        red_stats[b]["k_nonzero"].append(k_nonzero)
                        red_stats[b]["red_rate"].append(red_rate)
                        red_stats[b]["bottom25_share"].append(bottom25_share)
                        red_stats[b]["bottom50_share"].append(bottom50_share)


        rms_accept.append(rms_ok / m)
        for b in boost_up_list:
            boosted_accept[b].append(boosted_ok_count[b] / m)

    plt.figure()
    plt.plot(U_vals, rms_accept, marker="o", label="RMS")
    for b in boost_up_list:
        plt.plot(U_vals, boosted_accept[b], marker="o", label=f"Boost {int(round(100*b))}%")


    # ---- Annotate values at U = 1.0 ----
    if 1.0 in U_vals:
        idx = U_vals.index(1.0)
        print("\nAcceptance at U=1.0:")
        print(f"RMS: {rms_accept[idx]:.3f}")
        for b in boost_up_list:
            print(f"Boost {int(b*100)}%: {boosted_accept[b][idx]:.3f}")
    #     x_val = 1.0
    #
    #     # RMS value
    #     y_rms = rms_accept[idx]
    #     plt.annotate(f"{y_rms:.2f}",
    #                  (x_val, y_rms),
    #                  textcoords="offset points",
    #                  xytext=(6, -15),
    #                  ha="right",
    #                  fontsize=14)
    #
    #     # Boosted curves
    #     offsets = [-15, -15, -15, -15]   # stagger to avoid overlap
    #     for off, b in zip(offsets, boost_up_list):
    #         y_val = boosted_accept[b][idx]
    #         plt.annotate(f"{y_val:.2f}",
    #                      (x_val, y_val),
    #                      textcoords="offset points",
    #                      xytext=(6, off),
    #                      ha="right",
    #                      fontsize=14)
    plt.ylim(0.0, 1.05)
    plt.xticks(fontsize=16)
    plt.yticks(fontsize=16)
    plt.xlabel("Utilization", fontsize=18)
    plt.ylabel("Acceptance Ratio", fontsize=18)
    plt.grid(True, linewidth=0.5)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_png, dpi=200)
    print(f"[OK] Saved figure: {out_png}")

    # ---- Report reduction-structure summary at U = 1.0 ----
    if 1.0 in U_vals:
        print("\n[Reduction structure @ U=1.0 for Boosted-RM accepted sets]")
        for b in boost_up_list:
            ks = red_stats[b]["k_nonzero"]
            rr = red_stats[b]["red_rate"]
            b25 = red_stats[b]["bottom25_share"]
            b50 = red_stats[b]["bottom50_share"]

            if len(ks) == 0:
                print(f"  boost_up={b:.2f}: (no accepted sets captured)")
                continue

            k_mean = float(np.mean(ks))
            k_min = int(np.min(ks))
            k_max = int(np.max(ks))

            rr_mean = 100.0 * float(np.mean(rr))
            rr_q1   = 100.0 * float(np.quantile(rr, 0.25))
            rr_q3   = 100.0 * float(np.quantile(rr, 0.75))

            b25_mean = 100.0 * float(np.mean(b25))
            b50_mean = 100.0 * float(np.mean(b50))

            print(
                f"  boost_up={b:.2f}: "
                f"k_nonzero avg={k_mean:.2f} (min={k_min}, max={k_max}); "
                f"reduction_rate avg={rr_mean:.2f}% (IQR {rr_q1:.2f}–{rr_q3:.2f}%), "
                f"Δ share in lowest-priority: bottom25%={b25_mean:.1f}%, bottom50%={b50_mean:.1f}%"
            )
# ----------------------------
# CLI
# ----------------------------

def plot_from_saved_json(
        in_json: str,
        out_png_time_box: str,
        out_png_ub_box: str,
        out_png_comp_box: str,
        out_png_net_box: str,
        out_png_global_freq_box: str
) -> None:

    with open(in_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    xs = data["series"]["U"]
    raw = data["raw_samples_by_U"]

    box_time_data = []
    box_ub_data = []
    box_comp_data = []
    box_net_data = []
    box_energy_global_improvement = []

    for U in xs:
        key = f"{U:.2f}"
        samples = raw[key]

        box_time_data.append(samples["boost_used_time_pct"] or [0.0])
        box_ub_data.append(samples["boost_used_over_ub_pct"] or [0.0])
        box_comp_data.append(samples["comp_ratio"] or [float("nan")])
        box_net_data.append(samples["net_energy_per_slot"] or [0.0])
        box_energy_global_improvement.append(
            samples["global_freq_improvement_per_slot"] or [0.0]
        )

    # ---- Plotting section (same as before) ----


    def make_violin(data, ylabel, out_file):
        plt.figure()

        datasets = data[-3:]
        labels = xs[-3:]   # utilization values

        plt.violinplot(
            datasets,
            showmeans=True,
            showmedians=True,
            showextrema=True
        )

        plt.xticks(
            list(range(1, len(labels) + 1)),
            [f"{u:.2f}" for u in labels]
        )

        # ---- PRINT STATISTICS ----
        print("\nStatistics for:", ylabel)
        for u, d in zip(labels, datasets):
            mean = np.mean(d)
            median = np.median(d)
            mx = np.max(d)
            print(f"U={u:.2f} : mean={mean:.4f}, median={median:.4f}, max={mx:.4f}")

        plt.xlabel("Utilization", fontsize=18)
        plt.ylabel(ylabel, fontsize=18)
        plt.xticks(fontsize=16)
        plt.yticks(fontsize=16)
        plt.grid(True, linewidth=0.5)
        plt.tight_layout()
        plt.savefig(out_file, dpi=200)
        print(f"[OK] Saved figure: {out_file}")

    make_violin(
        box_time_data,
        "Boost-Time Percentage",
        out_png_time_box
    )

    make_violin(
        box_ub_data,
        "Boost Utilization (%)",
        out_png_ub_box
    )

    make_violin(
        box_comp_data,
        "Compensation Ratio",
        out_png_comp_box
    )

    make_violin(
        box_net_data,
        "Net Energy per Slot",
        out_png_net_box
    )

    make_violin(
        box_energy_global_improvement,
        "Dynamic Energy Improvement",
        out_png_global_freq_box
    )



def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    # generate
    ap_g = sub.add_parser("generate", help="Generate task sets and write to JSONL file")
    ap_g.add_argument("--out", type=str, required=True, help="Output JSONL file")
    ap_g.add_argument("--n", type=int, required=True)
    ap_g.add_argument("--umin", type=int, default=85)
    ap_g.add_argument("--umax", type=int, default=100)
    ap_g.add_argument("--ustep", type=int, default=5)
    ap_g.add_argument("--m", type=int, required=True, help="Task sets per utilization")
    ap_g.add_argument("--tmin", type=int, default=10)
    ap_g.add_argument("--tmax", type=int, default=200)
    ap_g.add_argument("--seed", type=int, default=1)

    # run
    ap_r = sub.add_parser("run", help="Run simulation reading task sets from JSONL file")
    ap_r.add_argument("--infile", type=str, required=True, help="Input JSONL file from generate step")
    ap_r.add_argument("--sb", type=float, default=1.5)
    ap_r.add_argument("--L", type=int, default=10)
    ap_r.add_argument("--seed", type=int, default=1)
    ap_r.add_argument("--fmin", type=float, default=1.3)
    ap_r.add_argument("--fmax", type=float, default=29.11)

    ap_r.add_argument("--out-png-time-box", type=str, default="boost_used_time_boxplot.png")
    ap_r.add_argument("--out-png-ub-box", type=str, default="boost_used_over_ub_boxplot.png")
    ap_r.add_argument("--out-png-comp-box", type=str, default="boost_comp_ratio_boxplot.png")
    ap_r.add_argument("--out-png-net-box", type=str, default="boost_net_energy_boxplot.png")
    ap_r.add_argument("--out-png-global-freq-box", type=str, default="boost_global_frequency_boxplot.png")
    ap_r.add_argument("--out-json", type=str, default="boost_boxplot_data.json")

    # diff
    ap_d = sub.add_parser("diff", help="Compare RMS vs Boosted-RM acceptance ratio under boost_up budgets")
    ap_d.add_argument("--infile", type=str, required=True, help="Input JSONL file from generate step")
    ap_d.add_argument("--sb", type=float, default=1.5)
    ap_d.add_argument("--boost-ups", type=str, default="0.05,0.10,0.20,0.30",
                      help="Comma-separated boost_up fractions, e.g., 0.05,0.10,0.20,0.30")
    ap_d.add_argument("--out-png", type=str, default="acceptance_ratio_diff.png")


    # plot
    ap_p = sub.add_parser("plot", help="Regenerate plots from saved JSON (no simulation)")
    ap_p.add_argument("--in-json", type=str, required=True,
                      help="Input JSON file produced by run step")
    ap_p.add_argument("--out-png-time-box", type=str,
                      default="boost_used_time_boxplot.png")
    ap_p.add_argument("--out-png-ub-box", type=str,
                      default="boost_used_over_ub_boxplot.png")
    ap_p.add_argument("--out-png-comp-box", type=str,
                      default="boost_comp_ratio_boxplot.png")
    ap_p.add_argument("--out-png-net-box", type=str,
                      default="boost_net_energy_boxplot.png")
    ap_p.add_argument("--out-png-global-freq-box", type=str,
                      default="boost_global_frequency_boxplot.png")


    args = ap.parse_args()

    if args.cmd == "generate":
        generate_to_file(
            out_path=args.out,
            n=args.n,
            umin=args.umin,
            umax=args.umax,
            ustep=args.ustep,
            m=args.m,
            Tmin=args.tmin,
            Tmax=args.tmax,
            seed=args.seed
        )

    elif args.cmd == "run":
        run_from_file(
            in_path=args.infile,
            sb=args.sb,
            Lruns=args.L,
            seed=args.seed,
            fmin=args.fmin,
            fmax=args.fmax,
            out_png_time_box=args.out_png_time_box,
            out_png_ub_box=args.out_png_ub_box,
            out_png_comp_box=args.out_png_comp_box,
            out_png_net_box=args.out_png_net_box,
            out_png_global_freq_box=args.out_png_global_freq_box,
            out_json=args.out_json
        )

    elif args.cmd == "diff":
        boost_up_list = [float(x.strip()) for x in args.boost_ups.split(",") if x.strip()]
        diff_from_file(
            in_path=args.infile,
            sb=args.sb,
            boost_up_list=boost_up_list,
            out_png=args.out_png
        )

    elif args.cmd == "plot":
        plot_from_saved_json(
            in_json=args.in_json,
            out_png_time_box=args.out_png_time_box,
            out_png_ub_box=args.out_png_ub_box,
            out_png_comp_box=args.out_png_comp_box,
            out_png_net_box=args.out_png_net_box,
            out_png_global_freq_box=args.out_png_global_freq_box
        )



if __name__ == "__main__":
    main()
