# Copyright (c) Facebook, Inc. and its affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

import torch
import torch.nn as nn
from torch import Tensor
from typing import List, Tuple
import copy

# Utilities to make nn.Module "functional"
# In particular the goal is to be able to provide a function that takes as input
# the parameters and evaluate the nn.Module using fixed inputs.


def _del_nested_attr(obj: nn.Module, names: List[str]) -> None:
    """
    Deletes the attribute specified by the given list of names.
    For example, to delete the attribute obj.conv.weight,
    use _del_nested_attr(obj, ['conv', 'weight'])
    """
    if len(names) == 1:
        delattr(obj, names[0])
    else:
        _del_nested_attr(getattr(obj, names[0]), names[1:])


def _set_nested_attr(obj: nn.Module, names: List[str], value: Tensor) -> None:
    """
    Set the attribute specified by the given list of names to value.
    For example, to set the attribute obj.conv.weight,
    use _del_nested_attr(obj, ['conv', 'weight'], value)
    """
    if len(names) == 1:
        setattr(obj, names[0], value)
    else:
        _set_nested_attr(getattr(obj, names[0]), names[1:], value)


def _get_nested_attr(obj: nn.Module, names: List[str]) -> None:
    if len(names) == 1:
        return getattr(obj, names[0])
    else:
        _get_nested_attr(getattr(obj, names[0]), names[1:])


def extract_weights(model):
    for module_name, m in model.named_modules():
        for param_name, p in list(m.named_parameters(recurse=False)):
            delattr(m, param_name)
            setattr(m, param_name, None)
            yield (module_name, m, param_name, p)

def load_weights(mod: nn.Module, names: List[str], params: Tuple[Tensor, ...], as_params=False) -> None:
    """
    Reload a set of weights so that `mod` can be used again to perform a forward pass.
    Note that the `params` are regular Tensors (that can have history) and so are left
    as Tensors. This means that mod.parameters() will still be empty after this call.
    """
    for name, p in zip(names, params):
        if as_params:
            p = nn.Parameter(p)
        _del_nested_attr(mod, name.split("."))
        _set_nested_attr(mod, name.split("."), p)


def _swap_state(mod: nn.Module, split_names: List[str], elems):
    result = []
    for split_name, elem in zip(split_names, elems):
        result.append(_get_nested_attr(mod, split_name))
        _del_nested_attr(mod, split_name)
        _set_nested_attr(mod, split_name, elem)
    return result


def extract_buffers(model):
    for module_name, m in model.named_modules():
        for buffer_name, b in list(m.named_buffers(recurse=False)):
            delattr(m, buffer_name)
            setattr(m, buffer_name, None)
            yield (module_name, m, buffer_name, b)


def load_buffers(mod: nn.Module, names: List[str], buffers: Tuple[Tensor, ...], as_params=False) -> None:
    for name, p in zip(names, buffers):
        _set_nested_attr(mod, name.split("."), p)


def load_state(
        model: nn.Module,
        weights: List[Tensor], weight_names: List[str],
        buffers=(), buffer_names=()):
    """load_state(model, weights, weight_names, buffers=(), buffer_names=()) -> model

    load_state takes `weights` and `buffers` and assigns them to the model.
    This is the inverse operation of `make_functional_deprecated_v1`.
    """
    assert len(weight_names) == len(weights)
    load_weights(model, weight_names, weights)
    if len(buffers) > 0:
        assert len(buffer_names) == len(buffers)
        load_buffers(model, buffer_names, buffers)
    return model


def make_functional_deprecated_v1(model: nn.Module):
    """make_functional_deprecated_v1(model) -> weights, func, weight_names

    Given an nn.Module, make_functional_deprecated_v1 extracts the state (weights)
    and returns a functional version of the model, `func`. This makes
    it so that it is possible use transforms over the parameters of
    `model`.

    `func` can be invoked as follows:
    ```
    x = torch.randn(4, 3)
    model = nn.Linear(3, 3)
    weights, func, _ = make_functional_deprecated_v1(model)
    func(weights, (x,))
    ```

    And here is an example of applying the grad transform:
    ```
    x = torch.randn(4, 3)
    model = nn.Linear(3, 3)
    weights, _, func = make_functional_deprecated_v1(model)
    grad_weights = grad(func)(weights, (x,))
    ```

    To put the state back into a model, use `load_state`.
    """
    buffers = list(model.buffers())
    if len(buffers) > 0:
        raise RuntimeError('make_functional_deprecated_v1(model): `model` has buffers. Please use '
                           'make_functional_with_buffers_deprecated_v1(model) instead.')
    weights, descriptors = extract_weights(model)

    def fun(weights, data):
        mutable_model = copy.deepcopy(model)
        load_weights(mutable_model, descriptors, weights)
        return mutable_model(*data)

    return weights, fun, descriptors


def make_functional_with_buffers_deprecated_v1(model: nn.Module):
    """make_functional_with_buffers_deprecated_v1(model) -> weights, buffers, func, weight_names, buffer_names

    Given an nn.Module, make_functional_with_buffers_deprecated_v1 extracts the state (weights and buffers)
    and returns a functional version of the model, `func`.

    `func` can be invoked as follows:
    ```
    x = torch.randn(4, 3)
    model = nn.Linear(3, 3)
    weights, buffers, func, _, _ = make_functional_with_buffers_deprecated_v1(model)
    func(weights, buffers, (x,))
    ```

    And here is an example of applying the grad transform:
    ```
    x = torch.randn(4, 3)
    model = nn.Linear(3, 3)
    weights, buffers, func, _, _ = make_functional_with_buffers_deprecated_v1(model)
    func(weights, buffers, (x,))
    grad_weights = grad(func)(weights, buffers, (x,))
    ```

    To put the state back into a model, use `load_state`.
    """
    weights, weight_descriptors = extract_weights(model)
    buffers, buf_descriptors = extract_buffers(model)

    def fun(weights, buffers, data):
        mutable_model = copy.deepcopy(model)
        load_weights(mutable_model, weight_descriptors, weights)
        load_buffers(mutable_model, buf_descriptors, buffers)
        return mutable_model(*data)

    return weights, buffers, fun, weight_descriptors, buf_descriptors


def make_split_names(lst):
    return [name.split('.') for name in lst]


class FunctionalModule(nn.Module):
    """
    This is the callable object returned by :func:`make_functional_with_buffers`.
    """

    def __init__(self, stateless_model, param_module_names, modules, param_names):
        super(FunctionalModule, self).__init__()
        self.stateless_model = stateless_model
        self.param_modules = modules
        self.param_names = param_names
        self.param_module_names = param_module_names

    @staticmethod
    def _create_from(model, disable_autograd_tracking=False):
        # TODO: We don't need to copy the model to create a stateless copy
        model_copy = copy.deepcopy(model)
        param_container = list(extract_weights(model_copy))
        if len(param_container):
            module_names, param_modules, param_names, params = zip(*param_container)
        else:
            module_names, param_modules, param_names, params = tuple(), tuple(), tuple(), tuple()
        if disable_autograd_tracking:
            for param in params:
                param.requires_grad_(False)

        return (
            FunctionalModule(model_copy, module_names, param_modules, param_names),
            params,
        )

    def forward(self, params, *args, **kwargs):
        old_params = []
        for module, param_name, param in zip(self.param_modules, self.param_names, params):
            old_params.append(getattr(module, param_name))
            delattr(module, param_name)
            setattr(module, param_name, param)

        try:
            return self.stateless_model(*args, **kwargs)
        finally:
            # Remove the loaded state on self.stateless_model
            for module, param_name, param in zip(self.param_modules, self.param_names, old_params):
                old_params.append(getattr(module, param_name))
                setattr(module, param_name, param)

    def __getstate__(self):
        state = self.__dict__.copy()
        state["param_modules"] = None
        return state

    def __setstate__(self, state):
        state["param_modules"] = []
        out = super().__setstate__(state)
        for module_name in self.param_module_names:
            found = False
            for other_name, module in self.stateless_model.named_modules():
                if other_name == module_name:
                    found = True
                    state["param_modules"].append(module)
                    break
            if not found:
                raise RuntimeError(f"module not found: {module_name}")
        return out

class FunctionalModuleWithBuffers(nn.Module):
    """
    This is the callable object returned by :func:`make_functional_with_buffers`.
    """

    def __init__(self, stateless_model, param_module_names, param_modules, param_names, buffer_module_names, buffer_modules, buffer_names):
        super(FunctionalModuleWithBuffers, self).__init__()
        self.stateless_model = stateless_model
        self.param_module_names = param_module_names
        self.param_modules = param_modules
        self.param_names = param_names
        self.buffer_module_names = buffer_module_names
        self.buffer_modules = buffer_modules
        self.buffer_names = buffer_names

    @staticmethod
    def _create_from(model, disable_autograd_tracking=False):
        # TODO: We don't need to copy the model to create a stateless copy
        model_copy = copy.deepcopy(model)
        param_container = list(extract_weights(model_copy))
        if len(param_container):
            param_module_names, param_modules, param_names, params = zip(*param_container)
        else:
            param_module_names, param_modules, param_names, params = tuple(), tuple(), tuple(), tuple()
        if disable_autograd_tracking:
            for param in params:
                param.requires_grad_(False)

        buffer_container = list(extract_buffers(model_copy))
        if len(buffer_container):
            buffer_module_names, buffer_modules, buffer_names, buffers = zip(*buffer_container)
        else:
            buffer_module_names, buffer_modules, buffer_names, buffers = tuple(), tuple(), tuple(), tuple()
        return (
            FunctionalModuleWithBuffers(
                model_copy,
                param_module_names,
                param_modules,
                param_names,
                buffer_module_names,
                buffer_modules,
                buffer_names),
            params,
            buffers,
        )

    def forward(self, params, buffers, *args, **kwargs):
        old_params = []
        for module, param_name, param in zip(self.param_modules, self.param_names, params):
            old_params.append(getattr(module, param_name))
            delattr(module, param_name)
            setattr(module, param_name, param)
        old_buffers = []
        for module, buffer_name, buffer in zip(self.buffer_modules, self.buffer_names, buffers):
            old_buffers.append(getattr(module, buffer_name))
            delattr(module, buffer_name)
            setattr(module, buffer_name, buffer)

        try:
            return self.stateless_model(*args, **kwargs)
        finally:
            # Remove the loaded state on self.stateless_model
            for module, param_name, param in zip(self.param_modules, self.param_names, old_params):
                old_params.append(getattr(module, param_name))
                setattr(module, param_name, param)
            for module, buffer_name, buffer in zip(self.buffer_modules, self.buffer_names, old_buffers):
                old_buffers.append(getattr(module, buffer_name))
                setattr(module, buffer_name, buffer)

    def __getstate__(self):
        state = self.__dict__.copy()
        state["param_modules"] = None
        state["buffer_modules"] = None
        return state

    def __setstate__(self, state):
        state["param_modules"] = []
        state["buffer_modules"] = []
        out = super().__setstate__(state)
        for module_name in self.param_module_names:
            found = False
            for other_name, module in self.stateless_model.named_modules():
                if other_name == module_name:
                    found = True
                    state["param_modules"].append(module)
                    break
            if not found:
                raise RuntimeError(f"module not found: {module_name}")
        for module_name in self.buffer_module_names:
            found = False
            for other_name, module in self.stateless_model.named_modules():
                if other_name == module_name:
                    found = True
                    state["buffer_modules"].append(module)
                    break
            if not found:
                raise RuntimeError(f"module not found: {module_name}")
        return out


def make_functional(model: nn.Module):
    """make_functional(model) -> func, params

    Given a ``torch.nn.Module``, :func:`make_functional` extracts the state
    (params) and returns a functional version of the model, ``func``. This
    makes it so that it is possible use transforms over the parameters of
    ``model``.

    ``func`` can be invoked as follows:

    .. code-block:: python

        import torch
        import torch.nn as nn
        from functorch import make_functional

        x = torch.randn(4, 3)
        model = nn.Linear(3, 3)
        func, params = make_functional(model)
        func(params, x)

    And here is an example of applying the grad transform over the parameters
    of a model.

    .. code-block:: python

        import torch
        import torch.nn as nn
        from functorch import make_functional, grad

        x = torch.randn(4, 3)
        t = torch.randn(4, 3)
        model = nn.Linear(3, 3)
        func, params = make_functional(model)

        def compute_loss(params, x, t):
            y = func(params, x)
            return nn.functional.mse_loss(y, t)

        grad_weights = grad(compute_loss)(params, x, t)

    If the model has any buffers, please use :func:`make_functional_with_buffers` instead.

    """
    buffers = list(model.buffers())
    if len(buffers) > 0:
        raise RuntimeError('make_functional(model): `model` has buffers. Please use '
                           'make_functional_with_buffers(model) instead.')
    return FunctionalModule._create_from(model)


def make_functional_with_buffers(model: nn.Module):
    """make_functional_with_buffers(model) -> func, params, buffers

    Given a ``torch.nn.Module``, make_functional_with_buffers extracts the
    state (params and buffers) and returns a functional version of the model
    ``func`` that can be invoked like a function.

    ``func`` can be invoked as follows:

    .. code-block:: python

        import torch
        import torch.nn as nn
        from functorch import make_functional_with_buffers

        x = torch.randn(4, 3)
        model = nn.Linear(3, 3)
        func, params, buffers = make_functional_with_buffers(model)
        func(params, buffers, x)

    And here is an example of applying the grad transform over the parameters
    of a model:

    .. code-block:: python

        import torch
        import torch.nn as nn
        from functorch import make_functional_with_buffers, grad

        x = torch.randn(4, 3)
        t = torch.randn(4, 3)
        model = nn.Linear(3, 3)
        func, params, buffers = make_functional_with_buffers(model)

        def compute_loss(params, buffers, x, t):
            y = func(params, buffers, x)
            return nn.functional.mse_loss(y, t)

        grad_weights = grad(compute_loss)(params, buffers, x, t)

    """
    return FunctionalModuleWithBuffers._create_from(model)


def transpose_stack(tuple_of_tuple_of_tensors):
    tuple_of_tuple_of_tensors = tuple(zip(*tuple_of_tuple_of_tensors))
    results = tuple(torch.stack(shards).detach() for shards in tuple_of_tuple_of_tensors)
    return results


def combine_state_for_ensemble(models):
    """combine_state_for_ensemble(models) -> func, params, buffers

    Prepares a list of torch.nn.Modules for ensembling with :func:`vmap`.

    Given a list of ``M`` ``nn.Modules`` of the same class, stacks all of their
    parameters and buffers together to make ``params`` and ``buffers``.
    Each parameter and buffer in the result will have an additional dimension
    of size ``M``.

    :func:`combine_state_for_ensemble` also returns ``func``, a functional
    version of one of the models in :attr:`models`. One cannot directly run
    ``func(params, buffers, *args, **kwargs)`` directly, you probably want to
    use ``vmap(func, ...)(params, buffers, *args, **kwargs)``

    Here's an example of how to ensemble over a very simple model:

    .. code-block:: python

        num_models = 5
        batch_size = 64
        in_features, out_features = 3, 3
        models = [torch.nn.Linear(in_features, out_features) for i in range(num_models)]
        data = torch.randn(batch_size, 3)

        fmodel, params, buffers = combine_state_for_ensemble(models)
        output = vmap(fmodel, (0, 0, None))(params, buffers, data)

        assert output.shape == (num_models, batch_size, out_features)

    """
    funcs, params, buffers = zip(*[make_functional_with_buffers(model)
                                   for model in models])
    params = transpose_stack(params)
    buffers = transpose_stack(buffers)
    return funcs[0], params, buffers


# class Ensemble(nn.Module):
#     def __init__(self, models, in_dims, out_dims=0):
#         super(Ensemble, self).__init__()
#         func_model, params, buffers = combine_state_for_ensemble(models)
#         self.func_model = func_model
#         self.params = params
#         self.buffers = buffers if len(buffers) > 0 else None
#
#         in_dims_start = (0, 0) if self.buffers is not None else (0,)
#         self.in_dims = in_dims_start + in_dims
#         self.out_dims = out_dims
#         self._vmap_func = vmap(func_model, self.in_dims, self.out_dims)
#
#     def forward(self, *args, **kwargs):
#         return self._vmap_func(self.params, self.buffers, *args, **kwargs)


def functional_init(model_class, ensemble_shape=(), device='cpu'):
    def wrapped(*args, **kwargs):
        if len(ensemble_shape) >= 2:
            raise ValueError('NYI: ensemble_shape with more than 1 element')
        if len(ensemble_shape) == 0:
            model = model_class(*args, **kwargs).to(device)
            return make_functional_deprecated_v1(model)
        num_models = ensemble_shape[0]
        if num_models <= 0:
            raise ValueError(f"num_models {num_models} should be > 0")
        # NB: Not very efficient, more of a POC
        models = tuple(model_class(*args, **kwargs).to(device)
                       for _ in range(num_models))
        _, fn, names = make_functional_deprecated_v1(model_class(*args, **kwargs))
        weights = tuple(make_functional_deprecated_v1(model)[0] for model in models)
        weights = tuple(zip(*weights))
        weights = tuple(torch.stack(shards).detach() for shards in weights)
        return weights, fn, names
    return wrapped


def functional_init_with_buffers(model_class, ensemble_shape=(), device='cpu'):
    def wrapped(*args, **kwargs):
        if len(ensemble_shape) >= 2:
            raise ValueError('NYI: ensemble_shape with more than 1 element')
        if len(ensemble_shape) == 0:
            model = model_class(*args, **kwargs).to(device)
            return make_functional_deprecated_v1(model)
        num_models = ensemble_shape[0]
        if num_models <= 0:
            raise ValueError(f"num_models {num_models} should be > 0")
        # NB: Not very efficient, more of a POC
        models = tuple(model_class(*args, **kwargs).to(device)
                       for _ in range(num_models))
        _, _, fn, weight_names, buffer_names = \
            make_functional_with_buffers_deprecated_v1(model_class(*args, **kwargs))
        weights, buffers = zip(*tuple(make_functional_with_buffers_deprecated_v1(model)[:2]
                                      for model in models))
        weights = tuple(zip(*weights))
        weights = tuple(torch.stack(shards).detach() for shards in weights)
        buffers = tuple(zip(*buffers))
        buffers = tuple(torch.stack(shards).detach() for shards in buffers)
        return weights, buffers, fn, weight_names, buffer_names
    return wrapped
