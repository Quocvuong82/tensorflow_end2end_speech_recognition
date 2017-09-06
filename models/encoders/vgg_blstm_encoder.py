#! /usr/bin/env python
# -*- coding: utf-8 -*-

"""VGG + Bidirectional LSTM encoder."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import math
import tensorflow as tf


class VGG_BLSTM_Encoder(object):
    """VGG + Bidirectional LSTM encoder.
    Args:
        num_unit: int, the number of units in each layer
        num_layer: int, the number of layers
        num_classes: int, the number of classes of target labels
            (except for a blank label)
        parameter_init: A float value. Range of uniform distribution to
            initialize weight parameters
        clip_activation: A float value. Range of activation clipping (> 0)
        num_proj: int, the number of nodes in recurrent projection layer
        bottleneck_dim: int, the dimensions of the bottleneck layer
        name: string, the name of encoder
    """

    def __init__(self,
                 num_unit,
                 num_layer,
                 num_classes,
                 splice=11,
                 parameter_init=0.1,
                 clip_activation=None,
                 num_proj=None,
                 bottleneck_dim=None,
                 name='vgg_blstm_encoder'):

        ctcBase.__init__(self, input_size, num_unit, num_layer, num_classes,
                         splice, parameter_init, clip_grad,
                         name)

        self.num_proj = int(num_proj) if num_proj not in [None, 0] else None
        self.bottleneck_dim = int(bottleneck_dim) if bottleneck_dim not in [
            None, 0] else None

    def __call__(self, inputs, inputs_seq_len, keep_prob_input,
                 keep_prob_hidden, keep_prob_output):
        """Construct model graph.
        Args:
            inputs: A tensor of size `[B, T, input_size]`
            inputs_seq_len: A tensor of size `[B]`
            keep_prob_input: A float value. A probability to keep nodes in
                the input-hidden layer
            keep_prob_hidden: A float value. A probability to keep nodes in
                the hidden-hidden layers
            keep_prob_output: A float value. A probability to keep nodes in
                the hidden-output layer
        Returns:
            logits: A tensor of size `[T, B, num_classes]`
            final_state: A final hidden state of the encoder
        """
        # inputs: 3D `[batch_size, max_time, input_size * splice]`
        batch_size = tf.shape(inputs)[0]
        max_time = tf.shape(inputs)[1]

        # Reshape to 4D `[batch_size, max_time, input_size, splice]`
        inputs = tf.reshape(
            inputs, shape=[batch_size, max_time, self.input_size, self.splice])

        # Reshape to 5D `[batch_size, max_time, input_size / 3, splice, 3 (+Δ,
        # ΔΔ)]`
        inputs = tf.reshape(
            inputs, shape=[batch_size, max_time, int(self.input_size / 3), 3, self.splice])
        inputs = tf.transpose(inputs, (0, 1, 2, 4, 3))

        # Reshape to 4D `[batch_size * max_time, input_size / 3, splice, 3]`
        inputs = tf.reshape(
            inputs, shape=[batch_size * max_time, int(self.input_size / 3), self.splice, 3])

        with tf.name_scope('VGG1'):
            inputs = self._conv_layer(inputs,
                                      filter_shape=[3, 3, 3, 64],
                                      name='conv1')
            inputs = self._conv_layer(inputs,
                                      filter_shape=[3, 3, 64, 64],
                                      name='conv2')
            inputs = self._max_pool(inputs, name='pool')
            # TODO: try batch normalization

        with tf.name_scope('VGG2'):
            inputs = self._conv_layer(inputs,
                                      filter_shape=[3, 3, 64, 128],
                                      name='conv1')
            inputs = self._conv_layer(inputs,
                                      filter_shape=[3, 3, 128, 128],
                                      name='conv2')
            inputs = self._max_pool(inputs, name='pool')
            # TODO: try batch normalization

        # Reshape to 5D `[batch_size, max_time, 11 (or 10), 3, 128]`
        inputs = tf.reshape(
            inputs, shape=[batch_size, max_time, math.ceil(self.input_size / 3 / 4), 3, 128])

        # Reshape to 3D `[batch_size, max_time, 11 (or 10) * 3 * 128]`
        inputs = tf.reshape(
            inputs, shape=[batch_size, max_time, math.ceil(self.input_size / 3 / 4) * 3 * 128])

        # Insert linear layer to recude CNN's output demention
        # from 11 (or 10) * 3 * 128 to 256
        with tf.name_scope('linear'):
            inputs = tf.contrib.layers.fully_connected(
                inputs=inputs,
                num_outputs=256,
                activation_fn=None,
                scope='linear')

        # Dropout for the VGG-output-hidden connection
        outputs = tf.nn.dropout(inputs,
                                keep_prob_input,
                                name='dropout_input')

        # Hidden layers
        for i_layer in range(self.num_layer):
            with tf.name_scope('blstm_hidden' + str(i_layer + 1)):
                # TODO: change to variable_scope

                initializer = tf.random_uniform_initializer(
                    minval=-self.parameter_init,
                    maxval=self.parameter_init)

                lstm_fw = tf.contrib.rnn.LSTMCell(
                    self.num_unit,
                    use_peepholes=True,
                    cell_clip=self.clip_activation,
                    initializer=initializer,
                    num_proj=self.num_proj,
                    forget_bias=1.0,
                    state_is_tuple=True)
                lstm_bw = tf.contrib.rnn.LSTMCell(
                    self.num_unit,
                    use_peepholes=True,
                    cell_clip=self.clip_activation,
                    initializer=initializer,
                    num_proj=self.num_proj,
                    forget_bias=1.0,
                    state_is_tuple=True)

                # Dropout for the hidden-hidden connections
                lstm_fw = tf.contrib.rnn.DropoutWrapper(
                    lstm_fw,
                    output_keep_prob=keep_prob_hidden)
                lstm_bw = tf.contrib.rnn.DropoutWrapper(
                    lstm_bw,
                    output_keep_prob=keep_prob_hidden)

                # _init_state_fw = lstm_fw.zero_state(self.batch_size,
                #                                     tf.float32)
                # _init_state_bw = lstm_bw.zero_state(self.batch_size,
                #                                     tf.float32)
                # initial_state_fw=_init_state_fw,
                # initial_state_bw=_init_state_bw,

                # Ignore 2nd return (the last state)
                (outputs_fw, outputs_bw), _ = tf.nn.bidirectional_dynamic_rnn(
                    cell_fw=lstm_fw,
                    cell_bw=lstm_bw,
                    inputs=outputs,
                    sequence_length=inputs_seq_len,
                    dtype=tf.float32,
                    scope='blstm_dynamic' + str(i_layer + 1))

                outputs = tf.concat(axis=2, values=[outputs_fw, outputs_bw])

        # Reshape to apply the same weights over the timesteps
        if self.num_proj is None:
            output_node = self.num_unit * 2
        else:
            output_node = self.num_proj * 2
        outputs = tf.reshape(outputs, shape=[-1, output_node])

        if self.bottleneck_dim is not None and self.bottleneck_dim != 0:
            with tf.name_scope('bottleneck'):
                # Affine
                W_bottleneck = tf.Variable(tf.truncated_normal(
                    shape=[output_node, self.bottleneck_dim],
                    stddev=0.1, name='W_bottleneck'))
                b_bottleneck = tf.Variable(tf.zeros(
                    shape=[self.bottleneck_dim], name='b_bottleneck'))
                outputs = tf.matmul(outputs, W_bottleneck) + b_bottleneck
                output_node = self.bottleneck_dim

                # Dropout for the hidden-output connections
                outputs = tf.nn.dropout(outputs,
                                        keep_prob_output,
                                        name='dropout_output_bottle')

        with tf.name_scope('output'):
            # Affine
            W_output = tf.Variable(tf.truncated_normal(
                shape=[output_node, self.num_classes],
                stddev=0.1, name='W_output'))
            b_output = tf.Variable(tf.zeros(
                shape=[self.num_classes], name='b_output'))
            logits_2d = tf.matmul(outputs, W_output) + b_output

            # Reshape back to the original shape
            logits = tf.reshape(
                logits_2d, shape=[batch_size, -1, self.num_classes])

            # Convert to time-major: `[max_time, batch_size, num_classes]'
            logits = tf.transpose(logits, (1, 0, 2))

            # Dropout for the hidden-output connections
            logits = tf.nn.dropout(logits,
                                   keep_prob_output,
                                   name='dropout_output')

            return logits

    def _max_pool(self, bottom, name):
        """A max pooling layer.
        Args:
            bottom: A tensor of size `[B * T, H, W, C]`
            name: A layer name
        Returns:
            A tensor of size `[B * T, H / 2, W / 2, C]`
        """
        return tf.nn.max_pool(
            bottom,
            ksize=[1, 2, 2, 1],  # original
            # ksize=[1, 3, 3, 1],
            strides=[1, 2, 2, 1],
            padding='SAME', name=name)

    def _conv_layer(self, bottom, filter_shape, name):
        """A convolutional layer
        Args:
            bottom: A tensor of size `[B * T, H, W, C]`
            filter_shape: A list of
                `[height, width, input_channel, output_channel]`
            name: A layer name
        Returns:
            outputs: A tensor of size `[B * T, H, W, output_channel]`
        """
        with tf.variable_scope(name):
            W = tf.Variable(tf.truncated_normal(shape=filter_shape,
                                                stddev=self.parameter_init),
                            name='weight')
            b = tf.Variable(tf.zeros(shape=filter_shape[-1]),
                            name='bias')
            conv_bottom = tf.nn.conv2d(bottom, W,
                                       strides=[1, 1, 1, 1],
                                       padding='SAME')
            outputs = tf.nn.bias_add(conv_bottom, b)
            return tf.nn.relu(outputs)
