from datetime import datetime
from functools import singledispatch
import os

import tensorflow as tf
from tensorflow.keras.layers import Layer


class Model:
    def __init__(self,
                 layers,
                 sess,
                 param_in=None,
                 param_out=None,
                 loss_fn=tf.nn.softmax_cross_entropy_with_logits_v2,
                 optimizer_cls=tf.train.AdamOptimizer,
                 learning_rate=0.001,
                 model_name="model"):
        assert len(layers) > 0 and [type(layer) is Layer for layer in layers]
        self._sess = sess
        self._x = None
        self._y = None
        self._out = None
        self._param_in = param_in
        self._param_out = param_out
        self._layers = layers
        self._params = None
        self._grads = None
        self._loss_fn = loss_fn
        self._loss_sym = None
        self._acc = None
        self._optimizer_cls = optimizer_cls
        self._learning_rate = learning_rate
        self._optimizer = self._optimizer_cls(self._learning_rate)
        self._optimize = None
        self._name = model_name
        self._saver = None
        self._gradients_sym = []
        self._weights_sym = []

    def build(self):
        self._x = tf.placeholder(**self._param_in)
        self._y = tf.placeholder(**self._param_out)
        self._out = self.build_forward_pass(self._x)
        self._loss_sym = self.build_loss(self._y, self._out)
        self._gradients_sym, self._weights_sym = self.build_compute_gradients(
            self._loss_sym)
        self.build_apply_gradients(self._gradients_sym)
        self._acc = self.build_accuracy(self._y, self._out)

    def get_variables(self):
        return tf.get_collection(
            tf.GraphKeys.GLOBAL_VARIABLES, scope="map/while/model")

    def _set_tensors(self, layer, use_tensors):
        if isinstance(layer, tf.keras.layers.Dense):
            for i in range(len(layer.weights)):
                if layer.weights[i].name in use_tensors:
                    if "kernel" in layer.weights[i].name:
                        layer.kernel = use_tensors[layer.weights[i].name]
                    elif "bias" in layer.weights[i].name:
                        layer.bias = use_tensors[layer.weights[i].name]

    def build_forward_pass(self, input_tensor, use_tensors=None, name=None):
        layer_in = input_tensor
        # Model layers
        with tf.variable_scope(
                name, default_name=self._name, values=[layer_in]):
            for layer in self._layers:
                if use_tensors:
                    self._set_tensors(layer, use_tensors)
                layer_out = layer(layer_in)
                layer_in = layer_out

        return layer_out

    def build_loss(self, label_placeholder, model_out, name=None):
        if not name:
            name = self._name + "_loss"
        with tf.variable_scope(name, values=[label_placeholder, model_out]):
            return self._loss_fn(label_placeholder, model_out)

    def build_gradients(self, loss_sym, fast_params=None):
        grads = {}
        params = {}
        if fast_params:
            for name, w in fast_params.items():
                params.update({name: w})
                grads.update({name: tf.gradients(loss_sym, w)[0]})
        else:
            for param in tf.get_collection(
                    tf.GraphKeys.GLOBAL_VARIABLES, scope="map/while/model"):
                # TODO: remove hard coded scope
                params.update({param.name: param})
                grads.update({param.name: tf.gradients(loss_sym, param)[0]})
        return grads, params

    def build_apply_gradients(self, gradients_sym):
        grad_var = [(g, w) for g, w in zip(gradients_sym, self._weights_sym)]
        self._optimize = self._optimizer.apply_gradients(grad_var)

    def build_accuracy(self, labels, output, name=None):
        with tf.variable_scope(
                name,
                default_name=self._name + "_accuracy",
                values=[labels, output]):
            y_pred = tf.math.argmax(output, axis=1)
            return tf.reduce_mean(
                tf.cast(tf.equal(y_pred, labels), tf.float32))

    def assign_model_params(self, params, name=None):
        if not name:
            name = self._name + "_assign_params"
        with tf.variable_scope(name, values=[params]):
            for i in tf.get_collection(
                    tf.GraphKeys.GLOBAL_VARIABLES, scope=self._name):
                if i.name in params:
                    i.assign(params[i.name])

    @property
    def loss_sym(self):
        return self._loss_sym

    @property
    def weights_sym(self):
        return self._loss_sym

    def compute_params_and_grads(self, x, y):
        feed_dict = {self._x: x, self._y: y}
        return self._sess.run(self._loss_out, feed_dict=feed_dict)

    def optimize(self, x, y):
        feed_dict = {self._x: x, self._y: y}
        self._sess.run([self._optimize], feed_dict=feed_dict)

    def compute_acc(self, x, y):
        feed_dict = {self._x: x, self._y: y}
        return self._sess.run(self._acc, feed_dict=feed_dict)

    def _set_saver(self):
        var_list = [
            var for var in tf.get_collection(
                tf.GraphKeys.TRAINABLE_VARIABLES, scope=self._name)
        ]
        self._saver = tf.train.Saver(var_list)

    def save_model(self):
        self._set_saver()
        model_path = "data/" + self._name + "_" + datetime.now().strftime(
            "%H_%M_%m_%d_%y")
        os.makedirs(model_path)
        self._saver.save(self._sess, model_path + "/" + self._name)

    def restore_model(self, save_path):
        self._set_saver()
        self._saver.restore(self._sess, save_path)