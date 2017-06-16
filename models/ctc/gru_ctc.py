#! /usr/bin/env python
# -*- coding: utf-8 -*-

"""GRU-CTC model."""

import tensorflow as tf
from .ctc_base import ctcBase


class GRU_CTC(ctcBase):
    """GRU-CTC model.
    Args:
        batch_size: int, batch size of mini batch
        input_size: int, the dimensions of input vectors
        num_unit: int, the number of units in each layer
        num_layer: int, the number of layers
        output_size: int, the number of nodes in softmax layer
            (except for blank class)
        parameter_init: A float value. Range of uniform distribution to
            initialize weight parameters
        clip_grad: A float value. Range of gradient clipping (> 0)
        clip_activation: A float value. Range of activation clipping (> 0)
        dropout_ratio_input: A float value. Dropout ratio in input-hidden
            layers
        dropout_ratio_hidden: A float value. Dropout ratio in hidden-hidden
            layers
        num_proj: not used
        weight_decay: A float value. Regularization parameter for weight decay
        bottleneck_dim: int, the dimensions of the bottleneck layer
    """

    def __init__(self,
                 batch_size,
                 input_size,
                 num_unit,
                 num_layer,
                 output_size,
                 parameter_init=0.1,
                 clip_grad=None,
                 clip_activation=None,
                 dropout_ratio_input=1.0,
                 dropout_ratio_hidden=1.0,
                 num_proj=None,  # not used
                 weight_decay=0.0,
                 bottleneck_dim=None,
                 name='gru_ctc'):

        ctcBase.__init__(self, batch_size, input_size, num_unit, num_layer,
                         output_size, parameter_init,
                         clip_grad, clip_activation,
                         dropout_ratio_input, dropout_ratio_hidden,
                         weight_decay, name)

        self.bottleneck_dim = bottleneck_dim

    def _build(self, inputs, inputs_seq_len):
        """Construct model graph.
        Args:
            inputs: A tensor of `[batch_size, max_time, input_dim]`
            inputs_seq_len:  A tensor of `[batch_size]`
        Returns:
            logits:
        """
        # Dropout for inputs
        self.keep_prob_input = tf.placeholder(tf.float32,
                                              name='keep_prob_input')
        self.keep_prob_hidden = tf.placeholder(tf.float32,
                                               name='keep_prob_hidden')
        inputs = tf.nn.dropout(inputs,
                               self.keep_prob_input,
                               name='dropout_input')

        # Hidden layers
        gru_list = []
        for i_layer in range(self.num_layer):
            with tf.name_scope('gru_hidden' + str(i_layer + 1)):

                initializer = tf.random_uniform_initializer(
                    minval=-self.parameter_init,
                    maxval=self.parameter_init)

                with tf.variable_scope('gru', initializer=initializer):
                    gru = tf.contrib.rnn.GRUCell(self.num_unit)

                # Dropout for outputs of each layer
                gru = tf.contrib.rnn.DropoutWrapper(
                    gru, output_keep_prob=self.keep_prob_hidden)

                gru_list.append(gru)

        # Stack multiple cells
        stacked_gru = tf.contrib.rnn.MultiRNNCell(
            gru_list, state_is_tuple=True)

        # Ignore 2nd return (the last state)
        outputs, _ = tf.nn.dynamic_rnn(cell=stacked_gru,
                                       inputs=inputs,
                                       sequence_length=inputs_seq_len,
                                       dtype=tf.float32)

        # `[batch_size, max_time, input_size_splice]`
        batch_size = tf.shape(inputs)[0]

        # Reshape to apply the same weights over the timesteps
        output_node = self.num_unit
        outputs = tf.reshape(outputs, shape=[-1, output_node])

        if self.bottleneck_dim is not None:
            with tf.name_scope('bottleneck'):
                # Affine
                W_bottleneck = tf.Variable(tf.truncated_normal(
                    shape=[output_node, self.bottleneck_dim],
                    stddev=0.1, name='W_bottleneck'))
                b_bottleneck = tf.Variable(tf.zeros(
                    shape=[self.bottleneck_dim], name='b_bottleneck'))
                outputs = tf.matmul(outputs, W_bottleneck) + b_bottleneck
                output_node = self.bottleneck_dim

        with tf.name_scope('output'):
            # Affine
            W_output = tf.Variable(tf.truncated_normal(
                shape=[output_node, self.num_classes],
                stddev=0.1, name='W_output'))
            b_output = tf.Variable(tf.zeros(
                shape=[self.num_classes], name='b_output'))
            logits_2d = tf.matmul(outputs, W_output) + b_output

            # Reshape back to the original shape
            logits_3d = tf.reshape(
                logits_2d, shape=[batch_size, -1, self.num_classes])

            # Convert to `[max_time, batch_size, num_classes]'
            logits = tf.transpose(logits_3d, (1, 0, 2))

            return logits
