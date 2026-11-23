"""
Cost calculation helper for Homework 1 and Capstone budget projections.
Based on Lesson 1.5 formula:
  Cost(N) = F + N * c
where:
  F = rate * (t_start + t_ready)   [Fixed startup cost]
  c = rate * t_gen                 [Marginal cost per asset]
  rate = hourly_rate / 3600        [USD per second]
"""

import argparse


def calculate_costs(
    hourly_rate: float,
    t_start: float,
    t_gen: float,
    n_assets: int,
    api_benchmark_cost: float,
):
    rate_per_sec = hourly_rate / 3600.0
    fixed_cost = rate_per_sec * t_start
    marginal_cost = rate_per_sec * t_gen
    total_cost = fixed_cost + n_assets * marginal_cost
    cost_per_asset = total_cost / n_assets if n_assets > 0 else 0.0

    # Projection at N = 1000
    n_projected = 1000
    total_projected = fixed_cost + n_projected * marginal_cost
    projected_per_asset = total_projected / n_projected

    # Breakeven against commercial per-call API
    # F + N * c = N * api_cost  =>  N = F / (api_cost - c)
    if api_benchmark_cost > marginal_cost:
        breakeven_n = fixed_cost / (api_benchmark_cost - marginal_cost)
    else:
        breakeven_n = float("inf")

    return {
        "rate_per_sec": rate_per_sec,
        "fixed_cost": fixed_cost,
        "marginal_cost": marginal_cost,
        "total_cost": total_cost,
        "cost_per_asset": cost_per_asset,
        "projected_cost_1000": total_projected,
        "projected_per_asset_1000": projected_per_asset,
        "breakeven_n": breakeven_n,
    }


def main():
    parser = argparse.ArgumentParser(description="Calculate GPU generation costs")
    parser.add_argument("--rate", type=float, default=1.5484, help="Hourly GPU rate in USD (default: L40S spot $1.5484)")
    parser.add_argument("--t_start", type=float, default=265.0, help="Startup + ready time in seconds")
    parser.add_argument("--t_gen", type=float, default=4.42, help="Median generation time per asset in seconds")
    parser.add_argument("--n", type=int, default=10, help="Number of assets generated in this run")
    parser.add_argument("--api_cost", type=float, default=0.005, help="Commercial API cost per asset in USD")
    args = parser.parse_args()

    results = calculate_costs(
        hourly_rate=args.rate,
        t_start=args.t_start,
        t_gen=args.t_gen,
        n_assets=args.n,
        api_benchmark_cost=args.api_cost,
    )

    print("=== Cost Breakdown ===")
    print(f"Hourly rate:              ${args.rate:.4f}/h (${results['rate_per_sec']:.6f}/s)")
    print(f"Fixed startup overhead:   ${results['fixed_cost']:.4f}")
    print(f"Marginal cost per asset:  ${results['marginal_cost']:.4f}")
    print(f"Total cost for N={args.n}:       ${results['total_cost']:.4f} (${results['cost_per_asset']:.4f}/asset)")
    print(f"Projected cost at N=1000: ${results['projected_cost_1000']:.4f} (${results['projected_per_asset_1000']:.4f}/asset)")
    if results["breakeven_n"] != float("inf"):
        print(f"Breakeven vs API (${args.api_cost:.4f}): N >= {int(results['breakeven_n']) + 1} assets")
    else:
        print(f"Breakeven vs API: Self-hosting marginal cost (${results['marginal_cost']:.4f}) exceeds API cost (${args.api_cost:.4f})")


if __name__ == "__main__":
    main()
