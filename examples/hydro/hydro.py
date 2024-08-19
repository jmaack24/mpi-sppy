# updated april 2020
# DLW: mpisppy version, May 2019
#
#  ___________________________________________________________________________
#
#  Pyomo: Python Optimization Modeling Objects
#  Copyright 2017 National Technology and Engineering Solutions of Sandia, LLC
#  Under the terms of Contract DE-NA0003525 with National Technology and 
#  Engineering Solutions of Sandia, LLC, the U.S. Government retains certain 
#  rights in this software.
#  This software is distributed under the 3-clause BSD License.
#  ___________________________________________________________________________

# started as elec3 from Pierre on 8 Dec 2010; removed scenarios
#
# Imports
#
import os
from pyomo.core import *  # the old fashioned way!
import mpisppy.phbase
import mpisppy.opt.ph
import mpisppy.opt.aph
import mpisppy.scenario_tree as scenario_tree
import pyomo.environ as pyo
from mpisppy.extensions.xhatspecific import XhatSpecific
import mpisppy.utils.sputils as sputils

##
## Setting up a Model
##
#
# Create the model
#
model = AbstractModel(name="elec3")

#
# Create sets used to define parameters
#

### etaps

model.nb_etap=Param(within=PositiveIntegers)

model.etap = RangeSet(1,model.nb_etap)

##
## Declaring Params
##
#
model.A=Param(model.etap)
model.D=Param(model.etap)

model.betaGt=Param()
model.betaGh=Param()
model.betaDns=Param()

model.PgtMax=Param()
model.PgtMin=Param()
model.PghMin=Param()
model.PghMax=Param()

model.VMin=Param()
model.VMax=Param()

model.u=Param(model.etap)
model.duracion=Param(model.etap)
model.V0=Param()
model.T=Param()


#bounds and variables

def Pgt_bounds(model, t):
    return(model.PgtMin,model.PgtMax)
model.Pgt = Var(model.etap, bounds=Pgt_bounds, within=NonNegativeReals)

def Pgh_bounds(model, t):
    return(model.PghMin,model.PghMax)
model.Pgh = Var(model.etap, bounds=Pgh_bounds, within=NonNegativeReals)

def PDns_bounds(model, t):
    return(0,model.D[t])
model.PDns = Var(model.etap, bounds=PDns_bounds, within=NonNegativeReals)

def Vol_bounds(model, t):
    return(model.VMin,model.VMax)
model.Vol = Var(model.etap, bounds=Vol_bounds, within=NonNegativeReals)

model.sl = Var(within=NonNegativeReals)

model.StageCost = Var(model.etap, within=Reals)

def discount_rule(model, t):
    # Be careful about integer division in python 2
    return (1/1.1)**(value(model.duracion[t])/float(value(model.T)))
model.r = Param(model.etap,initialize=discount_rule)


# objective

def StageCostRule(model, t):
    if t < value(model.nb_etap):
        return model.StageCost[t] == model.r[t] * (model.betaGt * model.Pgt[t] + \
                                     model.betaGh * model.Pgh[t] + \
                                     model.betaDns * model.PDns[t] )
    else:
        return model.StageCost[t] == (model.r[t] * (model.betaGt * model.Pgt[t] + \
                                     model.betaGh * model.Pgh[t] + \
                                     model.betaDns * model.PDns[t]) + model.sl)

model.StageCostConstraint = Constraint(model.etap, rule=StageCostRule)

# constraints

def fixpgh_rule(model):
    return model.Pgh[1] == 60
#model.testfixing = Constraint(rule=fixpgh_rule)

def demand_rule(model, t):
    return model.Pgt[t]+model.Pgh[t]+model.PDns[t]-model.D[t] == 0.0
model.demand= Constraint(model.etap, rule=demand_rule)

def conserv_rule(model, t):
    if t == 1:
        return model.Vol[t]-model.V0 <= model.u[t] *(model.A[t]-model.Pgh[t])
    else:
        return model.Vol[t]-model.Vol[t-1] <= model.u[t] *(model.A[t]-model.Pgh[t])
model.conserv= Constraint(model.etap, rule=conserv_rule)

def fcfe_rule(model):
    return model.sl>= 4166.67*(model.V0-model.Vol[3])
model.fcfe= Constraint(rule=fcfe_rule)


#
# PySP Auto-generated Objective
#
# minimize: sum of StageCosts
#
# A active scenario objective equivalent to that generated by PySP is
# included here for informational purposes.
def total_cost_rule(model):
    return sum_product(model.StageCost)
model.Objective_rule = Objective(rule=total_cost_rule, sense=minimize)

#=============================================================================
def MakeAllScenarioTreeNodes(model, bf):
    """ Make the tree nodes and put them in a dictionary.
        Assume three stages and a branching factor of bf.
        Note: this might not ever be called. (Except maybe for the EF)
        Note: mpisppy does not have leaf nodes.
        Aside: every rank makes their own nodes; these nodes do not 
        hold any data computed by a solution algorithm.
    """
    TreeNodes = dict()
    TreeNodes["ROOT"] = scenario_tree.ScenarioNode("ROOT",
                                                  1.0,
                                                  1,
                                                  model.StageCost[1],
                                                  [model.Pgt[1],
                                                   model.Pgh[1],
                                                   model.PDns[1],
                                                   model.Vol[1]],
                                                  model)
    for b in range(bf):
        ndn = "ROOT_"+str(b)
        TreeNodes[ndn] = scenario_tree.ScenarioNode(ndn,
                                                   1.0/bf,
                                                   2,
                                                   model.StageCost[2],
                                                  [model.Pgt[2],
                                                   model.Pgh[2],
                                                   model.PDns[2],
                                                   model.Vol[2]],
                                                    model,
                                                    parent_name="ROOT")

#=============================================================================
def MakeNodesforScen(model, BFs, scennum):
    """ Make just those scenario tree nodes needed by a scenario.
        Return them as a list.
        NOTE: the nodes depend on the scenario model and are, in some sense,
              local to it.
        Args:
            BFs (list of int): branching factors
    """
    # In general divide by the product of the branching factors that come after the node (here prod(BFs[1:])=BFs[1])
    ndn = "ROOT_"+str((scennum-1) // BFs[1]) # scennum is one-based
    retval = [scenario_tree.ScenarioNode("ROOT",
                                         1.0,
                                         1,
                                         model.StageCost[1],
                                         [model.Pgt[1],
                                          model.Pgh[1],
                                          model.PDns[1],
                                          model.Vol[1]],
                                         model),
              scenario_tree.ScenarioNode(ndn,
                                         1.0/BFs[0],
                                         2,
                                         model.StageCost[2],
                                         [model.Pgt[2],
                                          model.Pgh[2],
                                          model.PDns[2],
                                          model.Vol[2]],
                                         model, parent_name="ROOT")
              ]
    return retval

#=============================================================================
def scenario_creator(scenario_name, branching_factors=None, data_path=None):
    """ The callback needs to create an instance and then attach
    the PySP nodes to it in a list _mpisppy_node_list ordered by stages. 
    Optionally attach _PHrho.
    Args:
        scenario_name (str): root name of the scenario data file
        branching_factors (list of ints): the branching factors
        data_path (str, optional): Path to the Hydro data.
    """
    if data_path is None:
        hydro_dir = os.path.dirname(os.path.abspath(__file__))
        data_path = os.sep.join([hydro_dir, 'PySP', 'scenariodata'])
    if branching_factors is None:
        raise ValueError("Hydro scenario_creator requires branching_factors")

    snum = sputils.extract_num(scenario_name)

    fname = data_path + os.sep + scenario_name + '.dat'
    instance = model.create_instance(fname, name=scenario_name)

    instance._mpisppy_node_list = MakeNodesforScen(instance, branching_factors, snum)
    model._mpisppy_probability = "uniform"
    return instance

#=============================================================================
def scenario_denouement(rank, scenario_name, scenario):
    pass

#=============================================================================
# helper functions

#=========
def inparser_adder(cfg):
    cfg.multistage()
    cfg.add_to_config(name ="stage2EFsolvern",
                      description="Solver to use for xhatlooper stage2ef option (default None)",
                      domain = str,
                      default=None)
    cfg.add_to_config(name ="hydro_data_path",
                      description="Path to hydro data (seldom used; default None)",
                      domain = str,
                      default=None)


#=========
def scenario_names_creator(num_scens,start=0):
    # return the full list of num_scens scenario names
    # (We hope this doesn't get used much for a multistage problem)
    return [f"Scen{i+1}" for i in range(start, start+num_scens)]


#=========
def kw_creator(cfg):
    # (for Amalgamator): linked to the scenario_creator and inparser_adder
    kwargs = {"branching_factors": cfg.branching_factors,
              "data_path": cfg.hydro_data_path
              }
    return kwargs

def sample_tree_scen_creator(sname, stage, sample_branching_factors, seed,
                             given_scenario=None, **scenario_creator_kwargs):
    raise RuntimeError("sample_tree_scen_creator is not written yet for hydro; feel free to write it!")

# This main is for ad hoc testing by developers
if __name__ == "__main__":
    options = {}
    options["asynchronousPH"] = False
    options["solver_name"] = "cplex"
    options["PHIterLimit"] = 200
    options["defaultPHrho"] = 1
    options["convthresh"] = 0.0001
    options["subsolvedirectives"] = None
    options["verbose"] = False
    options["display_timing"] = True
    options["display_progress"] = True
    options["iter0_solver_options"] = None
    options["iterk_solver_options"] = None
    options["branching_factors"] = [3, 3]
    options["xhat_looper_options"] =  {"xhat_solver_options":\
                                         None,
                                         "scen_limit": 3,
                                         "dump_prefix": "delme",
                                         "csvname": "looper.csv"}

    # branching factor (3 stages is hard-wired)
    BFs = options["branching_factors"]
    ScenCount = BFs[0] * BFs[1]
    all_scenario_names = list()
    for sn in range(ScenCount):
        all_scenario_names.append("Scen"+str(sn+1))
    # end hardwire

    # This is multi-stage, so we need to supply node names
    all_nodenames = sputils.create_nodenames_from_branching_factors(BFs)

    # **** ef ****
    solver = pyo.SolverFactory(options["solver_name"])

    ef = sputils.create_EF(
        all_scenario_names,
        scenario_creator,
        scenario_creator_kwargs={"branching_factors": BFs},
    )
    results = solver.solve(ef, tee=options["verbose"])
    print('EF objective value:', pyo.value(ef.EF_Obj))
    sputils.ef_nonants_csv(ef, "vardump.csv")

    # **** ph ****
    options["xhat_specific_options"] = {"xhat_solver_options":
                                          options["iterk_solver_options"],
                                          "xhat_scenario_dict": \
                                          {"ROOT": "Scen1",
                                           "ROOT_0": "Scen1",
                                           "ROOT_1": "Scen4",
                                           "ROOT_2": "Scen7"},
                                          "csvname": "specific.csv"}

    # as of april 2020, we are not supporting xhat as an extension
    ph = mpisppy.opt.ph.PH(
        options,
        all_scenario_names,
        scenario_creator,
        scenario_denouement,
        scenario_creator_kwargs={"branching_factors": BFs},
        all_nodenames=all_nodenames,
    )
    
    conv, obj, tbound = ph.ph_main()
    if ph.cylinder_rank == 0:
        print("Trival bound =",tbound)

    ph._disable_W_and_prox()
    e_obj = ph.Eobjective()
    if ph.cylinder_rank == 0:
        print("unweighted e_obj={}".format(e_obj))

