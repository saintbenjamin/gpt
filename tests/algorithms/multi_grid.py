#!/usr/bin/env python3
#
# Authors: Daniel Richtmann 2020
#          Christoph Lehner 2020
#
# Desc.: Test multigrid for clover
#
import gpt as g
import numpy as np

# setup rng, mute
g.default.set_verbose("random", False)
rng = g.random("test_mg")

# just run with larger volume
L = [16, 8, 16, 16]

# setup gauge field
U = g.qcd.gauge.random(g.grid(L, g.double), rng)
g.message("Plaquette:", g.qcd.gauge.plaquette(U))

# quark
w_dp = g.qcd.fermion.wilson_clover(
    U,
    {
        "kappa": 0.137,
        "csw_r": 0,
        "csw_t": 0,
        "xi_0": 1,
        "nu": 1,
        "isAnisotropic": False,
        "boundary_phases": [1.0, 1.0, 1.0, 1.0],
    },
)
w_sp = w_dp.converted(g.single)

# default grid
grid = U[0].grid

# create source
src = g.vspincolor(grid)
src[:] = g.vspincolor([[1, 1, 1], [1, 1, 1], [1, 1, 1], [1, 1, 1]])

# abbreviations
i = g.algorithms.inverter
p = g.qcd.fermion.preconditioner

# mg setup parameters
mg_setup_2lvl_params = {
    "block_size": [[2, 2, 2, 2]],
    "n_block_ortho": 1,
    "check_block_ortho": True,
    "n_basis": 30,
    "make_hermitian": False,
    "save_links": True,
    "vector_type": "null",
    "n_pre_ortho": 1,
    "n_post_ortho": 0,
    "solver": i.fgmres(
        {"eps": 1e-3, "maxiter": 50, "restartlen": 25, "checkres": False}
    ),
    "distribution": rng.cnormal,
}
mg_setup_3lvl_params = {
    "block_size": [[2, 2, 2, 2], [2, 1, 1, 1]],
    "n_block_ortho": 1,
    "check_block_ortho": True,
    "n_basis": 30,
    "make_hermitian": False,
    "save_links": True,
    "vector_type": "null",
    "n_pre_ortho": 1,
    "n_post_ortho": 0,
    "solver": i.fgmres(
        {"eps": 1e-3, "maxiter": 50, "restartlen": 25, "checkres": False}
    ),
    "distribution": rng.cnormal,
}
g.message(f"mg_setup_2lvl = {mg_setup_2lvl_params}")
g.message(f"mg_setup_3lvl = {mg_setup_3lvl_params}")

# mg setup objects
mg_setup_2lvl_dp = i.multi_grid_setup(w_dp, mg_setup_2lvl_params)
mg_setup_3lvl_sp = i.multi_grid_setup(w_sp, mg_setup_3lvl_params)

# mg inner solvers
wrapper_solver = i.fgmres(
    {"eps": 1e-1, "maxiter": 10, "restartlen": 5, "checkres": False}
)
smooth_solver = i.fgmres(
    {"eps": 1e-14, "maxiter": 8, "restartlen": 4, "checkres": False}
)
coarsest_solver = i.fgmres(
    {"eps": 5e-2, "maxiter": 50, "restartlen": 25, "checkres": False}
)

# mg solver/preconditioner objects
vcycle_params = {
    "coarsest_solver": coarsest_solver,
    "smooth_solver": smooth_solver,
    "wrapper_solver": None,
}
kcycle_params = {
    "coarsest_solver": coarsest_solver,
    "smooth_solver": smooth_solver,
    "wrapper_solver": wrapper_solver,
}

mg_2lvl_vcycle_dp = i.sequence(
    i.multi_grid(coarsest_solver, *mg_setup_2lvl_dp[0]),
    i.calculate_residual(
        "before smoother"
    ),  # optional since it costs time but helps to tune MG solver
    smooth_solver,
    i.calculate_residual("after smoother"),  # optional
)

mg_3lvl_kcycle_sp = i.sequence(
    i.multi_grid(
        wrapper_solver.modified(
            prec=i.sequence(
                i.multi_grid(coarsest_solver, *mg_setup_3lvl_sp[1]), smooth_solver
            )
        ),
        *mg_setup_3lvl_sp[0],
    ),
    smooth_solver,
)

# outer solver
fgmres_params = {"eps": 1e-6, "maxiter": 1000, "restartlen": 20}

# preconditioned inversion (using only smoother, w/o coarse grid correction)
fgmres_outer = i.fgmres(fgmres_params, prec=smooth_solver)
sol_smooth = g.eval(fgmres_outer(w_dp) * src)
eps2 = g.norm2(w_dp * sol_smooth - src) / g.norm2(src)
niter_prec_smooth = len(fgmres_outer.history)
g.message("Test resid/iter fgmres + smoother:", eps2, niter_prec_smooth)
assert eps2 < 1e-12

# preconditioned inversion (2lvl mg -- vcycle -- double precision)
fgmres_outer = i.fgmres(fgmres_params, prec=mg_2lvl_vcycle_dp)
sol_prec_2lvl_mg_vcycle_dp = g.eval(fgmres_outer(w_dp) * src)

eps2 = g.norm2(w_dp * sol_prec_2lvl_mg_vcycle_dp - src) / g.norm2(src)
niter_prec_2lvl_mg_vcycle_dp = len(fgmres_outer.history)
g.message(
    "Test resid/iter fgmres + 2lvl vcycle mg double:",
    eps2,
    niter_prec_2lvl_mg_vcycle_dp,
)
assert eps2 < 1e-12
assert niter_prec_2lvl_mg_vcycle_dp <= niter_prec_smooth

# preconditioned inversion (3lvl mg -- kcycle -- mixed precision)
fgmres_outer = i.fgmres(
    fgmres_params,
    prec=i.mixed_precision(mg_3lvl_kcycle_sp, g.single, g.double),
)
sol_prec_3lvl_mg_kcycle_mp = g.eval(fgmres_outer(w_dp) * src)

eps2 = g.norm2(w_dp * sol_prec_3lvl_mg_kcycle_mp - src) / g.norm2(src)
niter_prec_3lvl_mg_kcycle_mp = len(fgmres_outer.history)
g.message(
    "Test resid/iter fgmres + 3lvl kcycle mg mixed:", eps2, niter_prec_3lvl_mg_kcycle_mp
)
assert eps2 < 1e-12
# assert niter_prec_3lvl_mg_kcycle_mp <= niter_prec_3lvl_mg_vcycle_mp
assert niter_prec_3lvl_mg_kcycle_mp < niter_prec_smooth

# print contributions to mg setup runtime
g.message("Contributions to time spent in MG setups")
for name, t in [
    ("2lvl_dp", mg_setup_2lvl_dp.t),
    ("3lvl_sp", mg_setup_3lvl_sp.t),
]:
    g.message(name + ":")
    for lvl in reversed(range(len(t))):
        g.message(t[lvl])

# print contributions to mg solve runtime
# g.message("Contributions to time spent in MG preconditioners")
# for name, t in [
#     ("2lvl_vcycle_dp", mg_2lvl_vcycle_dp.t),
#     ("3lvl_kcycle_sp", mg_3lvl_kcycle_sp.t),
# ]:
#     g.message(name + ":")
#     for lvl in reversed(range(len(t))):
#         g.message(t[lvl])

# # print average iteration counts / time per level
# g.message("Average iteration counts of inner solvers")
# for name, h in [
#     ("2lvl_vcycle_dp", mg_2lvl_vcycle_dp.history),
#     ("3lvl_kcycle_sp", mg_3lvl_kcycle_sp.history),
# ]:
#     for lvl in reversed(range(len(h))):
#         for k, v in h[lvl].items():
#             stats = list(map(lambda l: sum(l) / len(l), zip(*v)))
#             if stats:
#                 g.message(f"{name}: lvl {lvl}: {k:10s} = {int(stats[0])}")
