###############################################################################
# mpi-sppy: MPI-based Stochastic Programming in PYthon
#
# Copyright (c) 2024, Lawrence Livermore National Security, LLC, Alliance for
# Sustainable Energy, LLC, The Regents of the University of California, et al.
# All rights reserved. Please see the files COPYRIGHT.md and LICENSE.md for
# full copyright and license information.
###############################################################################
import numpy as np
import abc
import enum
import time
import os
import math

from mpisppy.cylinders.spwindow import SPWindow
from pyomo.environ import ComponentMap, Var
from mpisppy import MPI
from mpisppy.cylinders.spcommunicator import SendArray, RecvArray, SPCommunicator, communicator_array
from mpisppy.cylinders.spwindow import Field


class ConvergerSpokeType(enum.Enum):
    OUTER_BOUND = 1
    INNER_BOUND = 2
    W_GETTER = 3
    NONANT_GETTER = 4

class Spoke(SPCommunicator):
    def __init__(self, spbase_object, fullcomm, strata_comm, cylinder_comm, options=None):

        super().__init__(spbase_object, fullcomm, strata_comm, cylinder_comm, options)

        # self.local_write_id = 0
        # self.remote_write_id = 0

        # self.local_length = 0  # Does NOT include the + 1
        # self.remote_length = 0  # Length on hub; does NOT include + 1

        self.last_call_to_got_kill_signal = time.time()

        # All spokes need the SHUTDOWN field to know when to terminate. Just
        # register that here.
        self.shutdown = self.register_recv_field(Field.SHUTDOWN, 0, 1)

        return

    # def _make_windows(self, local_length, remote_length):
    #     # Spokes notify the hub of the buffer sizes
    #     pair_of_lengths = np.array([local_length, remote_length], dtype="i")
    #     self.strata_comm.Send((pair_of_lengths, MPI.INT), dest=0, tag=self.strata_rank)
    #     self.local_length = local_length
    #     self.remote_length = remote_length

    #     # Make the windows of the appropriate buffer sizes
    #     # To do?: Spoke should not need to know how many other spokes there are.
    #     # Just call a single _make_window()? Do you need to create empty
    #     # windows?
    #     # ANSWER (dlw July 2020): Since the windows have zero length and since
    #     # the number of spokes is not expected to be large, it is probably OK.
    #     # The (minor) benefit is that free_windows does not need to know if it
    #     # was called by a hub or a spoke. If we ever move to dynamic spoke
    #     # creation, then this needs to be reimagined.
    #     self.windows = [None for _ in range(self.n_spokes)]
    #     self.buffers = [None for _ in range(self.n_spokes)]
    #     for i in range(self.n_spokes):
    #         length = self.local_length if self.strata_rank == i + 1 else 0
    #         win, buff = self._make_window(length)
    #         self.windows[i] = win
    #         self.buffers[i] = buff

    #     buffer_spec = self.build_buffer_spec()
    #     self.window = SPWindow(buffer_spec, self.strata_comm)

    #     self._make_window(self.strata_comm)
    #     self._windows_constructed = True

    #     return

    # def buffer(self, field: Field) -> np.typing.ArrayLike:
    #     return self._locals[field]

    # def is_field_new(self, field: Field) -> bool:
    #     return self._new_locals[field]

    def spoke_to_hub(self, values: np.typing.NDArray, field: Field, write_id: int):
        """ Put the specified values into the locally-owned buffer for the hub
            to pick up.

            Notes:
                This automatically does the -1 indexing

                This assumes that values contains a slot at the end for the
                write_id
        """
        # expected_length = self.local_length + 1
        # if len(values) != expected_length:
        #     raise RuntimeError(
        #         f"Attempting to put array of length {len(values)} "
        #         f"into local buffer of length {expected_length}"
        #     )
        self.cylinder_comm.Barrier()
        # self.local_write_id += 1
        # values[-1] = self.local_write_id
        # window = self.windows[self.strata_rank - 1]
        # window.Lock(self.strata_rank)
        # window.Put((values, len(values), MPI.DOUBLE), self.strata_rank)
        # window.Unlock(self.strata_rank)
        values[-1] = write_id
        self.window.put(values, field)
        return

    def spoke_from_hub(self,
                       values: np.typing.NDArray,
                       field: Field,
                       last_write_id: int
                       ):
        """
        """
        # expected_length = self.remote_length + 1
        # if len(values) != expected_length:
        #     raise RuntimeError(
        #         f"Spoke trying to get buffer of length {expected_length} "
        #         f"from hub, but provided buffer has length {len(values)}."
        #     )
        # self.cylinder_comm.Barrier()
        # window = self.windows[self.strata_rank - 1]
        # window.Lock(0)
        # window.Get((values, len(values), MPI.DOUBLE), 0)
        # window.Unlock(0)

        self.cylinder_comm.Barrier()
        self.window.get(values, 0, field)

        # On rare occasions a NaN is seen...
        new_id = int(values[-1]) if not math.isnan(values[-1]) else 0
        local_val = np.array((new_id,-new_id), 'i')
        max_min_ids = np.zeros(2, 'i')
        self.cylinder_comm.Allreduce((local_val, MPI.INT),
                                     (max_min_ids, MPI.INT),
                                     op=MPI.MAX)

        max_id = max_min_ids[0]
        min_id = -max_min_ids[1]
        # NOTE: we only proceed if all the ranks agree
        #       on the ID
        if max_id != min_id:
            return False

        assert max_id == min_id == new_id

        # if (new_id > self.remote_write_id) or (new_id < 0):
        #     self.remote_write_id = new_id
        #     return True

        if new_id > last_write_id or new_id < 0:
            return True

        return False

    def _got_kill_signal(self):
        shutdown_buf = self._locals[self._make_key(Field.SHUTDOWN, 0)]
        if shutdown_buf.is_new():
            shutdown = (self.shutdown[0] == 1.0)
        else:
            shutdown = False
        ## End if
        # print("SHUTDOWN: ", self.shutdown[0],
        #       "  New: ", shutdown_buf.is_new(),
        #       "  RetVal: ", shutdown)
        return shutdown

    def got_kill_signal(self):
        """ Spoke should call this method at least every iteration
            to see if the Hub terminated
        """
        # return self._got_kill_signal()
        # self.window.get(self.shutdown, 0, Field.SHUTDOWN)
        self.update_locals()
        return self._got_kill_signal()

    @abc.abstractmethod
    def main(self):
        """
        The main call for the Spoke. Derived classe
        should call the got_kill_signal method
        regularly to ensure all ranks terminate
        with the Hub.
        """
        pass

    # def get_serial_number(self):
    #     return self.remote_write_id

    # @abc.abstractmethod
    def update_locals(self):
        for (key, recv_buf) in self._locals.items():
            field, rank = self._split_key(key)
            recv_buf._is_new = self.spoke_from_hub(recv_buf.array(), field, recv_buf.id())
            if recv_buf._is_new:
                recv_buf.pull_id()
            ## End if
        ## End for
        return

    # @abc.abstractmethod
    # def _got_kill_signal(self):
    #     """ Every spoke needs a way to get the signal to terminate
    #         from the hub
    #     """
    #     pass

    # @abc.abstractmethod
    # def init_local_buffer(self) -> None:
    #     """ Initialize buffers for local copies of hub values
    #     """
    #     pass


class _BoundSpoke(Spoke):
    """ A base class for bound spokes
    """
    def __init__(self, spbase_object, fullcomm, strata_comm, cylinder_comm, options=None):
        super().__init__(spbase_object, fullcomm, strata_comm, cylinder_comm, options)
        if self.cylinder_rank == 0 and \
                'trace_prefix' in spbase_object.options and \
                spbase_object.options['trace_prefix'] is not None:
            trace_prefix = spbase_object.options['trace_prefix']

            filen = trace_prefix+self.__class__.__name__+'.csv'
            if os.path.exists(filen):
                raise RuntimeError(f"Spoke trace file {filen} already exists!")
            with open(filen, 'w') as f:
                f.write("time,bound\n")
            self.trace_filen = filen
            self.start_time = spbase_object.start_time
        else:
            self.trace_filen = None

        # self._new_locals = False
        # self._bound = None
        # self._locals = None

        return

    # def make_windows(self):
    #     """ Makes the bound window and a remote window to
    #         look for a kill signal
    #     """
    #     self._make_windows(1, 2) # kill signals are accounted for in _make_window
    #     self._bound = communicator_array(1) # spoke bound + kill signal
    #     self._locals = communicator_array(2) # hub outer/inner bounds and kill signal


    @abc.abstractmethod
    def bound_type(self) -> Field:
        pass
        # # TODO: Does this work? Probably not...
        # if ConvergerSpokeType.OUTER_BOUND in self.converger_spoke_types:
        #     my_type = Field.OUTER_BOUND
        # elif ConvergerSpokeType.INNER_BOUND in self.converger_spoke_types:
        #     my_type = Field.INNER_BOUND
        # else:
        #     raise RuntimeError(f"Unabale to determine bound type {self.converger_spoke_types}")
        # return my_type


    def build_window_spec(self) -> dict[Field, int]:

        window_spec = dict()
        window_spec[self.bound_type()] = 1

        self._bound = self.register_send_field(self.bound_type(), 1)
        self._hub_bounds = self.register_recv_field(Field.BOUNDS, 0, 2)

        return window_spec


    @property
    def bound(self):
        return self._bound[0]

    @bound.setter
    def bound(self, value):
        self._append_trace(value)
        self._bound[0] = value
        sbuf = self._sends[self.bound_type()]
        self.spoke_to_hub(self._bound, self.bound_type(), sbuf.next_write_id())
        return

    @property
    def hub_inner_bound(self):
        """Returns the local copy of the inner bound from the hub"""
        # NOTE: This should be the same as _hub_bounds[1]
        return self._hub_bounds[-2]

    @property
    def hub_outer_bound(self):
        """Returns the local copy of the outer bound from the hub"""
        # NOTE: This should be the same as _hub_bounds[0]
        return self._hub_bounds[-3]

    # def update_locals(self):
    #     self._new_locals = self.spoke_from_hub([self._locals], [Field.BOUNDS])
    #     return

    # def _got_kill_signal(self):
    #     """Looks for the kill signal and returns True if sent"""
    #     self._new_locals = self.spoke_from_hub(self._locals)
    #     return self.remote_write_id == -1

    def _append_trace(self, value):
        if self.cylinder_rank != 0 or self.trace_filen is None:
            return
        with open(self.trace_filen, 'a') as f:
            f.write(f"{time.perf_counter()-self.start_time},{value}\n")


class _BoundNonantLenSpoke(_BoundSpoke):
    """ A base class for bound spokes which also
        want something of len nonants from OPT
    """

    # def __init__(self, spbase_object, fullcomm, strata_comm, cylinder_comm, options=None):
    #     super().__init__(spbase_object, fullcomm, strata_comm, cylinder_comm, options)
    #     self._local_nonant_len = None
    #     return

    # def make_windows(self):
    #     """ Makes the bound window and with a remote buffer long enough
    #         to hold an array as long as the nonants.

    #         Input:
    #             opt (SPBase): Must have local_scenarios attached already!

    #     """
    #     if not hasattr(self.opt, "local_scenarios"):
    #         raise RuntimeError("Provided SPBase object does not have local_scenarios attribute")

    #     if len(self.opt.local_scenarios) == 0:
    #         raise RuntimeError("Rank has zero local_scenarios")

    #     vbuflen = 2
    #     for s in self.opt.local_scenarios.values():
    #         vbuflen += len(s._mpisppy_data.nonant_indices)

    #     self._make_windows(1, vbuflen)
    #     self._bound = communicator_array(1)
    #     self._locals = communicator_array(vbuflen)

    @abc.abstractmethod
    def nonant_len_type(self) -> Field:
        # TODO: Make this a static method?
        pass

    def build_window_spec(self) -> dict[Field, int]:

        window_spec = super().build_window_spec()

        if not hasattr(self.opt, "local_scenarios"):
            raise RuntimeError("Provided SPBase object does not have local_scenarios attribute")
        ## End if

        if len(self.opt.local_scenarios) == 0:
            raise RuntimeError("Rank has zero local_scenarios")
        ## End if

        vbuflen = 0
        for s in self.opt.local_scenarios.values():
            vbuflen += len(s._mpisppy_data.nonant_indices)
        ## End for

        self.register_recv_field(self.nonant_len_type(), 0, vbuflen)

        return window_spec


class InnerBoundSpoke(_BoundSpoke):
    """ For Spokes that provide an inner bound through self.bound to the
        Hub, and do not need information from the main PH OPT hub.
    """
    converger_spoke_types = (ConvergerSpokeType.INNER_BOUND,)
    converger_spoke_char = 'I'

    def bound_type(self) -> Field:
        return Field.INNER_BOUND


class OuterBoundSpoke(_BoundSpoke):
    """ For Spokes that provide an outer bound through self.bound to the
        Hub, and do not need information from the main PH OPT hub.
    """
    converger_spoke_types = (ConvergerSpokeType.OUTER_BOUND,)
    converger_spoke_char = 'O'

    def bound_type(self) -> Field:
        return Field.OUTER_BOUND


class _BoundWSpoke(_BoundNonantLenSpoke):
    """ A base class for bound spokes which also want the W's from the OPT
        threads
    """

    def nonant_len_type(self) -> Field:
        return Field.DUALS

    # def build_window_spec(self) -> dict[Field, int]:
    #     window_spec = super().build_window_spec()
    #     self.register_recv_field(Field.DUALS, )
    #     return window_spec

    @property
    def localWs(self):
        """Returns the local copy of the weights"""
        # return self._locals[:-3] # -3 for the bounds and kill signal
        # return self._local_nonant_len[:-1] # -1 to ignore the read_id
        key = self._make_key(Field.DUALS, 0)
        return self._locals[key].array()

    @property
    def new_Ws(self):
        """ Returns True if the local copy of
            the weights has been updated since
            the last call to got_kill_signal
        """
        key = self._make_key(Field.DUALS, 0)
        return self._locals[key].is_new()

    # def update_locals(self):
    #     # self.spoke_from_hub(self._locals, Field.BOUNDS)
    #     # self._new_locals = self.spoke_from_hub(self._local_nonant_len, Field.DUALS)
    #     # self._new_locals = self.spoke_from_hub([self._locals, self._local_nonant_len],
    #     #                                        [Field.BOUNDS, Field.DUALS])
    #     return


class OuterBoundWSpoke(_BoundWSpoke):
    """
    For Spokes that provide an outer bound
    through self.bound to the Hub,
    and receive the Ws (or weights) from
    the main PH OPT hub.
    """

    converger_spoke_types = (
        ConvergerSpokeType.OUTER_BOUND,
        ConvergerSpokeType.W_GETTER,
    )
    converger_spoke_char = 'O'

    def bound_type(self) -> Field:
        return Field.OUTER_BOUND


class _BoundNonantSpoke(_BoundNonantLenSpoke):
    """ A base class for bound spokes which also
        want the xhat's from the OPT threads
    """

    def nonant_len_type(self) -> Field:
        return Field.NONANT

    @property
    def localnonants(self):
        """Returns the local copy of the nonants"""
        # return self._locals[:-3]
        # return self._local_nonant_len[:-1] # -1 to avoid returning the read_id
        key = self._make_key(Field.NONANT, 0)
        return self._locals[key].array()

    @property
    def new_nonants(self):
        """Returns True if the local copy of
           the nonants has been updated since
           the last call to got_kill_signal"""
        # return self._new_locals[Field.NONANT]
        key = self._make_key(Field.NONANT, 0)
        return self._locals[key].is_new()

    # def update_locals(self):
    #     # self.spoke_from_hub(self._locals, Field.BOUNDS)
    #     # self._new_locals = self.spoke_from_hub(self._local_nonant_len, Field.NONANT)
    #     # self._new_locals = self.spoke_from_hub([self._locals, self._local_nonant_len],
    #     #                                        [Field.BOUNDS, Field.NONANT])
    #     return


class InnerBoundNonantSpoke(_BoundNonantSpoke):
    """ For Spokes that provide an inner (incumbent)
        bound through self.bound to the Hub,
        and receive the nonants from
        the main SPOpt hub.

        Includes some helpful methods for saving
        and restoring results
    """
    converger_spoke_types = (
        ConvergerSpokeType.INNER_BOUND,
        ConvergerSpokeType.NONANT_GETTER,
    )
    converger_spoke_char = 'I'

    def __init__(self, spbase_object, fullcomm, strata_comm, cylinder_comm, options=None):
        super().__init__(spbase_object, fullcomm, strata_comm, cylinder_comm, options)
        self.is_minimizing = self.opt.is_minimizing
        self.best_inner_bound = math.inf if self.is_minimizing else -math.inf
        self.solver_options = None # can be overwritten by derived classes

        # set up best solution cache
        for k,s in self.opt.local_scenarios.items():
            s._mpisppy_data.best_solution_cache = None

    def update_if_improving(self, candidate_inner_bound):
        if candidate_inner_bound is None:
            return False
        update = (candidate_inner_bound < self.best_inner_bound) \
                if self.is_minimizing else \
                (self.best_inner_bound < candidate_inner_bound)
        if not update:
            return False

        self.best_inner_bound = candidate_inner_bound
        # send to hub
        self.bound = candidate_inner_bound
        self._cache_best_solution()
        return True

    def finalize(self):
        for k,s in self.opt.local_scenarios.items():
            if s._mpisppy_data.best_solution_cache is None:
                return None
            for var, value in s._mpisppy_data.best_solution_cache.items():
                var.set_value(value, skip_validation=True)

        self.opt.first_stage_solution_available = True
        self.opt.tree_solution_available = True
        self.final_bound = self.bound
        return self.final_bound

    def _cache_best_solution(self):
        for k,s in self.opt.local_scenarios.items():
            scenario_cache = ComponentMap()
            for var in s.component_data_objects(Var):
                scenario_cache[var] = var.value
            s._mpisppy_data.best_solution_cache = scenario_cache

    def bound_type(self) -> Field:
        return Field.INNER_BOUND



class OuterBoundNonantSpoke(_BoundNonantSpoke):
    """ For Spokes that provide an outer
        bound through self.bound to the Hub,
        and receive the nonants from
        the main OPT hub.
    """
    converger_spoke_types = (
        ConvergerSpokeType.OUTER_BOUND,
        ConvergerSpokeType.NONANT_GETTER,
    )
    converger_spoke_char = 'A'  # probably Lagrangian

    def bound_type(self) -> Field:
        return Field.OUTER_BOUND
