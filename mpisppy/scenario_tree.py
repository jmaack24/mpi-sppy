###############################################################################
# mpi-sppy: MPI-based Stochastic Programming in PYthon
#
# Copyright (c) 2024, Lawrence Livermore National Security, LLC, Alliance for
# Sustainable Energy, LLC, The Regents of the University of California, et al.
# All rights reserved. Please see the files COPYRIGHT.md and LICENSE.md for
# full copyright and license information.
###############################################################################
# scenario_tree.py; PySP 2.0 scenario structure
# ALL INDEXES ARE ZERO-BASED
import logging

import pyomo.environ as pyo
import mpisppy.utils.sputils as sputils
from pyomo.core.base.indexed_component_slice import IndexedComponent_slice

logger = logging.getLogger('mpisppy.scenario_tree')

def build_vardatalist(self, model, varlist=None):
    """
    Convert a list of pyomo variables to a list of SimpleVar and _GeneralVarData. If varlist is none, builds a
    list of all variables in the model. Written by CD Laird

    Parameters
    ----------
    model: ConcreteModel
    varlist: None or list of pyo.Var
    """
    vardatalist = None

    # if the varlist is None, then assume we want all the active variables
    if varlist is None:
        raise RuntimeError("varlist is None in scenario_tree.build_vardatalist")
        vardatalist = [v for v in model.component_data_objects(pyo.Var, active=True, sort=True)]
    elif isinstance(varlist, (pyo.Var, IndexedComponent_slice)):
        # user provided a variable, not a list of variables. Let's work with it anyway
        varlist = [varlist]

    if vardatalist is None:
        # expand any indexed components in the list to their
        # component data objects
        vardatalist = list()
        for v in varlist:
            if isinstance(v, IndexedComponent_slice):
                vardatalist.extend(v.__iter__())
            elif v.is_indexed():
                vardatalist.extend((v[i] for i in sorted(v.keys())))
            else:
                vardatalist.append(v)
    return vardatalist
    
class ScenarioNode:
    """Store a node in the scenario tree.

    Note:
      This can only be created programatically from a scenario
      creation function. (maybe that function reads data)

    Args:
      name (str): name of the node; one node must be named "ROOT"
      cond_prob (float): conditional probability
      stage (int): stage number (root is 1)
      cost_expression (pyo Expression or Var):  stage cost 
      nonant_list (list of pyo Var, Vardata or slices): the Vars that
              require nonanticipativity at the node (might not be a list)
      scen_model (pyo concrete model): the (probably not 'a') concrete model
      nonant_ef_suppl_list (list of pyo Var, Vardata or slices):
              vars for which nonanticipativity constraints tighten the EF
              (important for bundling)
      parent_name (str): name of the parent node      

    Lists:
      nonant_vardata(list of vardata objects): vardatas to blend
      x_bar_list(list of floats): bound by index to nonant_vardata
    """
    def __init__(self, name, cond_prob, stage, cost_expression,
                 nonant_list, scen_model, nonant_ef_suppl_list=None,
                 parent_name=None):
        """Initialize a ScenarioNode object. Assume most error detection is
        done elsewhere.
        """
        self.name = name
        self.cond_prob = cond_prob
        self.stage = stage
        self.cost_expression = cost_expression
        self.nonant_list = nonant_list
        self.nonant_ef_suppl_list = nonant_ef_suppl_list
        self.parent_name = parent_name # None for ROOT
        # now make the vardata lists
        if self.nonant_list is not None:
            self.nonant_vardata_list = sputils.build_vardatalist(
                                                         scen_model,
                                                         self.nonant_list)
        else:
            logger.warning("nonant_list is empty for node {},".format(name) +\
                    "No nonanticipativity will be enforced at this node by default")
            self.nonant_vardata_list = []

        if self.nonant_ef_suppl_list is not None:
            self.nonant_ef_suppl_vardata_list = sputils.build_vardatalist(
                                                         scen_model,
                                                         self.nonant_ef_suppl_list)
        else:
            self.nonant_ef_suppl_vardata_list = []
