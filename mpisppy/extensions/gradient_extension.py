# Copyright 2023 by U. Naepels and D.L. Woodruff
# This software is distributed under the 3-clause BSD License.

import os
import time
import numpy as np
import pyomo.environ as pyo

import mpisppy.MPI as MPI
import mpisppy.extensions.extension
import mpisppy.utils.gradient as grad
import mpisppy.utils.find_rho as find_rho
import mpisppy.utils.sputils as sputils
from mpisppy.utils.wtracker import WTracker
from mpisppy import global_toc


class Gradient_extension(mpisppy.extensions.extension.Extension):
    """
    This extension makes PH use gradient-rho and the corresponding rho setter.
    
    Args:
       opt (PHBase object): gives the problem
       cfg (Config object): config object
    
    Attributes:
       grad_object (Find_Grad object): gradient object
    
    """
    def __init__(self, opt, comm=None):
        super().__init__(opt)
        self.cylinder_rank = self.opt.cylinder_rank
        self.cfg = opt.options["gradient_extension_options"]["cfg"]
        # This is messy because we want to be able to use or give rhos as requested.
        # (e.g., if the user gave us an input file, use that)
        # TBD: stop using files
        # TBD: restore the rho_setter?
        self.cfg_args_cache = {'rho_file_in': self.cfg.rho_file_in,
                               'grad_rho_file_out': self.cfg.grad_rho_file_out,
                               'rho_setter': self.cfg.grad_rho_setter}
        if self.cfg.get('grad_cost_file_out', ifmissing="") == "":
            self.cfg.grad_cost_file_out = './_temp_grad_cost_file.csv'
        else:
            self.cfg_args_cache["grad_cost_file_out"] = self.cfg.grad_cost_file_out
        if self.cfg.get('grad_cost_file_in', ifmissing="") == "":
            self.cfg.grad_cost_file_in = self.cfg.grad_cost_file_out  # write then read
        # from the perspective of this extension, we really should not have both
        if self.cfg.get('rho_file_in', ifmissing="") == "":
            if self.cfg.get("grad_rho_file_out", ifmissing="") == "":
                # we don't have either, but will write then read
                self.cfg.grad_rho_file_out = './_temp_rho_file.csv'
                self.cfg.rho_file_in = self.cfg.grad_rho_file_out  
            else:
                # we don't have an in, but we have an out, still write then read
                self.cfg.rho_file_in = self.cfg.grad_rho_file_out

        self.grad_object = grad.Find_Grad(opt, self.cfg)
        self.rho_setter = find_rho.Set_Rho(self.cfg).rho_setter
        self.primal_conv_cache = []
        self.dual_conv_cache = []
        self.wt = WTracker(self.opt)

    def _display_rho_values(self):
        for sname, scenario in self.opt.local_scenarios.items():
            rho_list = [scenario._mpisppy_model.rho[ndn_i]._value
                      for ndn_i, _ in scenario._mpisppy_data.nonant_indices.items()]
            print(sname, 'rho values: ', rho_list[:5])
            break

    def _display_W_values(self):
        for (sname, scenario) in self.opt.local_scenarios.items():
            W_list = [w._value for w in scenario._mpisppy_model.W.values()]
            print(sname, 'W values: ', W_list)
            break

    def _update_rho_primal_based(self):
        curr_conv, last_conv = self.primal_conv_cache[-1], self.primal_conv_cache[-2]
        primal_diff =  np.abs((last_conv - curr_conv) / last_conv)
        return (primal_diff <= 0.05)

    def _update_rho_dual_based(self):
        curr_conv, last_conv = self.dual_conv_cache[-1], self.dual_conv_cache[-2]
        dual_diff =  np.abs((last_conv - curr_conv) / last_conv) if last_conv != 0 else 0
        #print(f'{dual_diff =}')
        return (dual_diff <= 0.05)


    def pre_iter0(self):
        pass

    def post_iter0(self):
        global_toc("Using gradient-based rho setter")
        self.primal_conv_cache.append(self.opt.convergence_diff())
        self.dual_conv_cache.append(self.wt.W_diff())
        self._display_rho_values()

    def miditer(self):
        self.primal_conv_cache.append(self.opt.convergence_diff())
        self.dual_conv_cache.append(self.wt.W_diff())
        if self.opt._PHIter == 1:
            self.grad_object.write_grad_cost()
        if self._update_rho_dual_based():
            self.grad_object.write_grad_rho()
            rho_setter_kwargs = self.opt.options['rho_setter_kwargs'] \
                                if 'rho_setter_kwargs' in self.opt.options \
                                   else dict()
            for sname, scenario in self.opt.local_scenarios.items():
                rholist = self.rho_setter(scenario, **rho_setter_kwargs)
                for (vid, rho) in rholist:
                    (ndn, i) = scenario._mpisppy_data.varid_to_nonant_index[vid]
                    scenario._mpisppy_model.rho[(ndn, i)] = rho
            self._display_rho_values()


    def enditer(self):
        pass

    def post_everything(self):
        # if we are using temp files, deal with it
        if self.cylinder_rank == 0 and os.path.exists(self.cfg.rho_file_in)\
           and self.cfg.rho_file_in != self.cfg_args_cache['rho_file_in']:
            os.remove(self.cfg.rho_file_in)
            self.cfg.rho_file_in = self.cfg_args_cache['rho_file_in']  # namely ""
        if self.cylinder_rank == 0 and os.path.exists(self.cfg.grad_cost_file_out)\
           and self.cfg.grad_cost_file_out != self.cfg_args_cache['grad_cost_file_out']:
            os.remove(self.cfg.grad_cost_file_out)
        self.cfg.grad_cost_file_out = self.cfg_args_cache['grad_cost_file_out']
