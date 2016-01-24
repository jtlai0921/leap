# -*- coding: utf-8 -*-
from __future__ import division

__copyright__ = """
Copyright (C) 2007-15 Andreas Kloeckner
Copyright (C) 2014 Matt Wala
"""

__license__ = """
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""

import numpy as np
import numpy.linalg as la
import pytest
from pytools import memoize_method
from leap.multistep.multirate import (
        rhs_policy,
        RHS,
        MultiRateMultiStepMethod,
        TwoRateAdamsBashforthMethod,
        TextualSchemeExplainer)


from utils import (  # noqa
        python_method_impl_interpreter as pmi_int,
        python_method_impl_codegen as pmi_cg)


class MultirateTimestepperAccuracyChecker(object):
    """Check that the multirate timestepper has the advertised accuracy."""

    def __init__(self, method, order, step_ratio, static_dt, ode, method_impl,
                 display_dag=False, display_solution=False):
        self.method = method
        self.order = order
        self.step_ratio = step_ratio
        self.static_dt = static_dt
        self.ode = ode
        self.method_impl = method_impl
        self.display_dag = display_dag
        self.display_solution = display_solution

    @memoize_method
    def get_code(self):
        stepper = TwoRateAdamsBashforthMethod(
                self.method, self.order, self.step_ratio,
                static_dt=self.static_dt)

        return stepper.generate()

    def initialize_method(self, dt):
        # Requires a coupled component.
        def make_coupled(f2f, f2s, s2f, s2s):
            def coupled(t, y):
                args = (t, y[0] + y[1], y[2] + y[3])
                return np.array((f2f(*args), f2s(*args), s2f(*args),
                    s2s(*args)),)
            return coupled

        function_map = {'<func>f2f': self.ode.f2f_rhs,
            '<func>s2f': self.ode.s2f_rhs, '<func>f2s': self.ode.f2s_rhs,
            '<func>s2s': self.ode.s2s_rhs, '<func>coupled': make_coupled(
                self.ode.f2f_rhs, self.ode.s2f_rhs, self.ode.f2s_rhs,
                self.ode.s2s_rhs)}

        print(self.get_code())
        method = self.method_impl(self.get_code(), function_map=function_map)

        t = self.ode.t_start
        y = self.ode.initial_values
        method.set_up(t_start=t, dt_start=dt,
                context={'fast': y[0], 'slow': y[1]})
        return method

    def get_error(self, dt, name=None, plot_solution=False):
        final_t = self.ode.t_end

        method = self.initialize_method(dt)

        times = []
        slow = []
        fast = []
        for event in method.run(t_end=final_t):
            if isinstance(event, method.StateComputed):
                if event.component_id == "slow":
                    slow.append(event.state_component)
                    times.append(event.t)
                elif event.component_id == "fast":
                    fast.append(event.state_component)

        assert abs(times[-1] - final_t) < 1e-10

        if 0:
            import matplotlib.pyplot as pt
            pt.plot(times, slow)
            pt.plot(times, self.ode.soln_1(times))
            pt.show()

        t = times[-1]
        y = (fast[-1], slow[-1])

        from multirate_test_systems import Basic, Tria

        if isinstance(self.ode, Basic) or isinstance(self.ode, Tria):
            # AK: why?
            if self.display_solution:
                self.plot_solution(times, fast, self.ode.soln_0)
            return abs(y[0]-self.ode.soln_0(t))
        else:
            from math import sqrt
            if self.display_solution:
                self.plot_solution(times, fast, self.ode.soln_0)
                self.plot_solution(times, slow, self.ode.soln_1)
            return abs(sqrt(y[0]**2 + y[1]**2)
                    - sqrt(self.ode.soln_0(t)**2 + self.ode.soln_1(t)**2))

    def show_dag(self):
        from dagrt.language import show_dependency_graph
        show_dependency_graph(self.get_code())

    def plot_solution(self, times, values, soln, label=None):
        import matplotlib.pyplot as pt
        pt.plot(times, values, label="comp")
        pt.plot(times, soln(times), label="true")
        pt.legend(loc='best')
        pt.show()

    def __call__(self):
        """Run the test and output the estimated the order of convergence."""

        from pytools.convergence import EOCRecorder

        if self.display_dag:
            self.show_dag()

        eocrec = EOCRecorder()
        for n in range(6, 8):
            dt = 2**(-n)
            error = self.get_error(dt, "mrab-%d.dat" % self.order)
            eocrec.add_data_point(dt, error)

        print("------------------------------------------------------")
        print("ORDER %d" % self.order)
        print("------------------------------------------------------")
        print(eocrec.pretty_print())

        orderest = eocrec.estimate_order_of_convergence()[0, 1]
        assert orderest > self.order*0.70


@pytest.mark.slowtest
@pytest.mark.parametrize("order", [1, 3])
@pytest.mark.parametrize("system", [
        #"Basic",
        "Full",
        #"Comp",
        #"Tria"
        ])
@pytest.mark.parametrize("method_name", TwoRateAdamsBashforthMethod.methods)
@pytest.mark.parametrize("static_dt", [True, False])
def test_multirate_accuracy(method_name, order, system, static_dt, step_ratio=2):
    """Check that the multirate timestepper has the advertised accuracy"""

    import multirate_test_systems

    system = getattr(multirate_test_systems, system)

    print("------------------------------------------------------")
    print("METHOD: %s" % method_name)
    print("------------------------------------------------------")

    MultirateTimestepperAccuracyChecker(
        method_name, order, step_ratio, static_dt=static_dt,
        ode=system(),
        method_impl=pmi_cg)()


def test_single_rate_identical(order=3):
    from leap.multistep import AdamsBashforthMethod
    from dagrt.exec_numpy import NumpyInterpreter

    from multirate_test_systems import Full
    ode = Full()

    t_start = 0
    dt = 0.1

    # {{{ single rate

    single_rate_method = AdamsBashforthMethod("y", order=order)
    single_rate_code = single_rate_method.generate()

    def single_rate_rhs(t, y):
        f, s = y
        return np.array([
            ode.f2f_rhs(t, f, s)+ode.s2f_rhs(t, f, s),
            ode.f2s_rhs(t, f, s)+ode.s2s_rhs(t, f, s),
            ])

    single_rate_interp = NumpyInterpreter(
            single_rate_code,
            function_map={"<func>y": single_rate_rhs})

    single_rate_interp.set_up(t_start=t_start, dt_start=dt,
            context={"y": np.array([
                ode.soln_0(t_start),
                ode.soln_1(t_start),
                ])})

    single_rate_values = {}

    nsteps = 20

    for event in single_rate_interp.run():
        if isinstance(event, single_rate_interp.StateComputed):
            single_rate_values[event.t] = event.state_component

            if len(single_rate_values) == nsteps:
                break

    # }}}

    # {{{ two rate

    multi_rate_method = MultiRateMultiStepMethod(
                order,
                component_names=("fast", "slow",),
                rhss=(
                    (
                        RHS(1, "<func>f", ("fast", "slow",)),
                        ),
                    (
                        RHS(1, "<func>s", ("fast", "slow",),
                            rhs_policy=rhs_policy.late),
                        ),)
                )
    multi_rate_code = multi_rate_method.generate()

    def rhs_fast(t, fast, slow):
        return ode.f2f_rhs(t, fast, slow)+ode.s2f_rhs(t, fast, slow)

    def rhs_slow(t, fast, slow):
        return ode.f2s_rhs(t, fast, slow)+ode.s2s_rhs(t, fast, slow)

    multi_rate_interp = NumpyInterpreter(
            multi_rate_code,
            function_map={"<func>f": rhs_fast, "<func>s": rhs_slow})

    multi_rate_interp.set_up(t_start=t_start, dt_start=dt,
            context={
                "fast": ode.soln_0(t_start),
                "slow": ode.soln_1(t_start),
                })

    multi_rate_values = {}

    for event in multi_rate_interp.run():
        if isinstance(event, single_rate_interp.StateComputed):
            idx = {"fast": 0, "slow": 1}[event.component_id]
            if event.t not in multi_rate_values:
                multi_rate_values[event.t] = [None, None]

            multi_rate_values[event.t][idx] = event.state_component

            if len(multi_rate_values) > nsteps:
                break

    # }}}

    times = sorted(single_rate_values)
    single_rate_values = np.array([single_rate_values[t] for t in times])
    multi_rate_values = np.array([multi_rate_values[t] for t in times])
    print(single_rate_values)
    print(multi_rate_values)

    diff = la.norm((single_rate_values-multi_rate_values).reshape(-1))

    assert diff < 1e-13


@pytest.mark.parametrize("method_name", ["F", "Fqsr", "Srsf", "S"])
def test_2rab_scheme_explainers(method_name, order=3, step_ratio=3,
        explainer=TextualSchemeExplainer()):
    stepper = TwoRateAdamsBashforthMethod(
            method_name, order=order, step_ratio=step_ratio)
    stepper.generate(explainer=explainer)
    print(explainer)


def test_mrab_scheme_explainers(order=3, step_ratio=3,
        explainer=TextualSchemeExplainer()):
    stepper = MultiRateMultiStepMethod(
                order,
                component_names=("fast", "slow",),
                rhss=(
                    (
                        RHS(1, "<func>f", ("fast", "slow",)),
                        ),
                    (
                        RHS(step_ratio, "<func>s", ("fast", "slow",),
                            rhs_policy=rhs_policy.late),
                        ),)
                )

    stepper.generate(explainer=explainer)
    print(explainer)


def test_dot(order=3, step_ratio=3, method_name="F", show=False):
    stepper = TwoRateAdamsBashforthMethod(
            method_name, order=order, step_ratio=step_ratio)
    code = stepper.generate()

    from dagrt.language import get_dot_dependency_graph
    print(get_dot_dependency_graph(code))

    if show:
        from dagrt.language import show_dependency_graph
        show_dependency_graph(code)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        exec(sys.argv[1])
    else:
        from py.test.cmdline import main
        main([__file__])

# vim: foldmethod=marker
