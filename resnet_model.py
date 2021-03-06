import tensorflow as tf
import tensorflow.contrib.eager as tfe
import numpy as np
from glob import glob

from colorama import Fore, Style
import time

# eager execution
tfe.enable_eager_execution(device_policy=tfe.DEVICE_PLACEMENT_SILENT)

# Hyper parameters
LEARNING_RATE = 0.01

layers = tf.keras.layers

LEARNING_RATE = 0.01
layers = tf.keras.layers


class _IdentityBlock(tf.keras.Model):
    """_IdentityBlock is the block that has no conv layer at shortcut.
    Args:
      kernel_size: the kernel size of middle conv layer at main path
      filters: list of integers, the filters of 3 conv layer at main path
      stage: integer, current stage label, used for generating layer names
      block: 'a','b'..., current block label, used for generating layer names
      data_format: data_format for the input ('channels_first' or
        'channels_last').
    """

    def __init__(self, kernel_size, filters, stage, block):
        super(_IdentityBlock, self).__init__(name='')
        filters1, filters2, filters3 = filters

        conv_name_base = 'res' + str(stage) + block + '_branch'
        bn_name_base = 'bn' + str(stage) + block + '_branch'
        bn_axis = 1

        self.conv2a = layers.Conv2D(
            filters1, (1, 1), name=conv_name_base + '2a')
        self.bn2a = layers.BatchNormalization(
            axis=bn_axis, name=bn_name_base + '2a')

        self.conv2b = layers.Conv2D(
            filters2,
            kernel_size,
            padding='same',
            name=conv_name_base + '2b')
        self.bn2b = layers.BatchNormalization(
            axis=bn_axis, name=bn_name_base + '2b')

        self.conv2c = layers.Conv2D(
            filters3, (1, 1), name=conv_name_base + '2c')
        self.bn2c = layers.BatchNormalization(
            axis=bn_axis, name=bn_name_base + '2c')

    def __call__(self, input_tensor, training=False):
        return self.call(input_tensor=input_tensor, training=training)

    def call(self, input_tensor, training=False):
        x = self.conv2a(input_tensor)
        x = self.bn2a(x, training=training)
        x = tf.nn.relu(x)

        x = self.conv2b(x)
        x = self.bn2b(x, training=training)
        x = tf.nn.relu(x)

        x = self.conv2c(x)
        x = self.bn2c(x, training=training)

        x += input_tensor
        return tf.nn.relu(x)


class _ConvBlock(tf.keras.Model):
    """_ConvBlock is the block that has a conv layer at shortcut.
    Args:
        kernel_size: the kernel size of middle conv layer at main path
        filters: list of integers, the filters of 3 conv layer at main path
        stage: integer, current stage label, used for generating layer names
        block: 'a','b'..., current block label, used for generating layer names
        data_format: data_format for the input ('channels_first' or
          'channels_last').
        strides: strides for the convolution. Note that from stage 3, the first
         conv layer at main path is with strides=(2,2), and the shortcut should
         have strides=(2,2) as well.
    """

    def __init__(self,
                 kernel_size,
                 filters,
                 stage,
                 block,
                 strides=(2, 2)):
        super(_ConvBlock, self).__init__(name='')
        filters1, filters2, filters3 = filters

        conv_name_base = 'res' + str(stage) + block + '_branch'
        bn_name_base = 'bn' + str(stage) + block + '_branch'
        bn_axis = 1

        self.conv2a = layers.Conv2D(
            filters1, (1, 1),
            strides=strides,
            name=conv_name_base + '2a')

        self.bn2a = layers.BatchNormalization(
            axis=bn_axis, name=bn_name_base + '2a')

        self.conv2b = layers.Conv2D(
            filters2,
            kernel_size,
            padding='same',
            name=conv_name_base + '2b')

        self.bn2b = layers.BatchNormalization(
            axis=bn_axis, name=bn_name_base + '2b')

        self.conv2c = layers.Conv2D(
            filters3, (1, 1), name=conv_name_base + '2c')
        self.bn2c = layers.BatchNormalization(
            axis=bn_axis, name=bn_name_base + '2c')

        self.conv_shortcut = layers.Conv2D(
            filters3, (1, 1),
            strides=strides,
            name=conv_name_base + '1')

        self.bn_shortcut = layers.BatchNormalization(
            axis=bn_axis, name=bn_name_base + '1')

    def __call__(self, input_tensor, training=False):
        return self.call(input_tensor=input_tensor, training=training)

    def call(self, input_tensor, training=False):
        x = self.conv2a(input_tensor)
        x = self.bn2a(x, training=training)
        x = tf.nn.relu(x)

        x = self.conv2b(x)
        x = self.bn2b(x, training=training)
        x = tf.nn.relu(x)

        x = self.conv2c(x)
        x = self.bn2c(x, training=training)

        shortcut = self.conv_shortcut(input_tensor)
        shortcut = self.bn_shortcut(shortcut, training=training)

        x += shortcut
        return tf.nn.relu(x)


class DVectorNet(tf.keras.Model):
    def __init__(self, input_dim, out_dim, checkpoint_directory, batch_size=32, device_name="cpu:0"):
        super(DVectorNet, self).__init__()

        self.input_dim = input_dim
        self.out_dim = out_dim
        self.checkpoint_directory = checkpoint_directory
        self.batch_size = batch_size
        self.device_name = device_name

        def conv_block(filters, stage, block, strides=(2, 2)):
            return _ConvBlock(
                3,
                filters,
                stage=stage,
                block=block,
                strides=strides)

        def id_block(filters, stage, block):
            return _IdentityBlock(
                3, filters, stage=stage, block=block)

        self.conv1 = layers.Conv2D(
            64, (7, 7),
            strides=(2, 2),
            padding='same',
            name='conv1')

        bn_axis = 1

        self.bn_conv1 = layers.BatchNormalization(axis=bn_axis, name='bn_conv1')
        self.max_pool = layers.MaxPooling2D(
            (3, 3), strides=(2, 2))

        self.l2a = conv_block([64, 64, 256], stage=2, block='a', strides=(1, 1))
        self.l2b = id_block([64, 64, 256], stage=2, block='b')
        self.l2c = id_block([64, 64, 256], stage=2, block='c')

        self.l3a = conv_block([128, 128, 512], stage=3, block='a')
        self.l3b = id_block([128, 128, 512], stage=3, block='b')
        self.l3c = id_block([128, 128, 512], stage=3, block='c')
        self.l3d = id_block([128, 128, 512], stage=3, block='d')

        self.l4a = conv_block([256, 256, 1024], stage=4, block='a')
        self.l4b = id_block([256, 256, 1024], stage=4, block='b')
        self.l4c = id_block([256, 256, 1024], stage=4, block='c')
        self.l4d = id_block([256, 256, 1024], stage=4, block='d')
        self.l4e = id_block([256, 256, 1024], stage=4, block='e')
        self.l4f = id_block([256, 256, 1024], stage=4, block='f')

        self.l5a = conv_block([512, 512, 2048], stage=5, block='a')
        self.l5b = id_block([512, 512, 2048], stage=5, block='b')
        self.l5c = id_block([512, 512, 2048], stage=5, block='c')

        self.avg_pool = layers.AveragePooling2D(
            (7, 7), strides=(7, 7))

        self.flatten = layers.Flatten()
        self.dense1 = layers.Dense(256, name='dense1', activation=tf.nn.relu)
        self.dense2 = layers.Dense(128, name='dense2', activation=tf.nn.relu)
        self.dvector = layers.Dense(64, name='dvector', activation=tf.nn.relu)

        self.fc1000 = layers.Dense(out_dim, name='fc1000')

        self.optimizer = tf.train.AdamOptimizer(learning_rate=LEARNING_RATE)

        self.time = time.time()
        self.total_step = 0
        self.loss_sum = 0

    def call(self, input_tensor, training=False):
        x = self.conv1(input_tensor)
        x = self.bn_conv1(x, training=training)
        x = tf.nn.relu(x)
        x = self.max_pool(x)

        x = self.l2a(x, training=training)
        x = self.l2b(x, training=training)
        x = self.l2c(x, training=training)

        x = self.l3a(x, training=training)
        x = self.l3b(x, training=training)
        x = self.l3c(x, training=training)
        x = self.l3d(x, training=training)

        x = self.l4a(x, training=training)
        x = self.l4b(x, training=training)
        x = self.l4c(x, training=training)
        x = self.l4d(x, training=training)
        x = self.l4e(x, training=training)
        x = self.l4f(x, training=training)

        x = self.l5a(x, training=training)
        x = self.l5b(x, training=training)
        x = self.l5c(x, training=training)

        #         print x.shape
        #         x = self.avg_pool(x)
        x = self.dense1(x)
        x = self.dense2(x)
        x = self.dvector(self.flatten(x))

        x = self.fc1000(x)
        return x

    def predict(self, X, training=False):
        x = self.conv1(X)
        x = self.bn_conv1(x, training=training)

        x = tf.nn.relu(x)
        x = self.max_pool(x)

        x = self.l2a(x, training=training)
        x = self.l2b(x, training=training)
        x = self.l2c(x, training=training)

        x = self.l3a(x, training=training)
        x = self.l3b(x, training=training)
        x = self.l3c(x, training=training)
        x = self.l3d(x, training=training)

        x = self.l4a(x, training=training)
        x = self.l4b(x, training=training)
        x = self.l4c(x, training=training)
        x = self.l4d(x, training=training)
        x = self.l4e(x, training=training)
        x = self.l4f(x, training=training)

        x = self.l5a(x, training=training)
        x = self.l5b(x, training=training)
        x = self.l5c(x, training=training)

        #         x = self.avg_pool(x)

        x = self.dvector(self.flatten(x))
        x = self.fc1000(x)
        return x

    def loss(self, x, target, training=False):
        predictions = self.predict(x, training=training)
        loss_value = tf.losses.sparse_softmax_cross_entropy(logits=predictions, labels=target)
        self.loss_sum += loss_value
        return loss_value

    def grads(self, x, target, training=False):
        with tfe.GradientTape() as tape:
            loss_value = self.loss(x, target, training=training)
        return tape.gradient(loss_value, self.variables)

    def fit(self,
            train_data=None,
            eval_data=None,
            epochs=500,
            verbose=1,
            **kwargs):

        train_acc = tfe.metrics.Accuracy('train_acc')
        eval_acc = tfe.metrics.Accuracy('eval_acc')

        self.history = {}
        self.history['train_acc'] = []
        self.history['eval_acc'] = []

        with tf.device(self.device_name):
            for i in range(epochs):
                self.total_step += 1
                self.loss_sum = 0
                temp = False

                for X, y in tfe.Iterator(train_data):
                    if i == 0 and temp:
                        print(self.predict(X=X, training=False)[0])
                    grads = self.grads(x=X, target=y, training=True)

                    if i == 0 and temp:
                        print("grads=======")
                        print(grads)
                        print "==========="
                        temp = False

                    self.optimizer.apply_gradients(zip(grads, self.variables))
                temp = True
                if (i == 0) | ((i + 1) % verbose == 0):
                    for X, y in tfe.Iterator(train_data):
                        logits = self.predict(X=X, training=False)
                        preds = tf.argmax(logits, axis=1)
                        if temp:
                            print(logits[0])
                            print(preds[0], y[0])
                            temp = False
                        train_acc(preds, y)

                    self.history['train_acc'].append(train_acc.result().numpy())

                    # Reset metrics
                    train_acc.init_variables()

                    # Check accuracy eval dataset
                    temp = [0 for j in range(NUM_CLASS)]
                    for X, y in tfe.Iterator(eval_data):
                        logits = self.predict(X=X, training=False)
                        preds = tf.argmax(logits, axis=1)
                        for lab in preds.numpy():
                            temp[lab] += 1
                        eval_acc(preds, y)
                    print(temp)

                    self.history['eval_acc'].append(eval_acc.result().numpy())

                    # Reset metrics
                    eval_acc.init_variables()
                    print(Fore.CYAN + '[EPOCH %d]/%.2fsec ============================' % (
                    (i + 1), time.time() - self.time))
                    self.time = time.time()
                    print(Fore.MAGENTA + 'Train accuracy at step %d: %5f%%' % (
                        self.total_step, 100.0 * self.history['train_acc'][-1]))
                    print(Fore.BLUE + 'Eval  accuracy at step %d: %5f%%' % (
                        self.total_step, 100.0 * self.history['eval_acc'][-1]))
                    print(Fore.RED + 'Loss     value at step %d: %5f' % (
                    self.total_step, self.loss_sum) + Style.RESET_ALL)
                    self.save(global_step=self.total_step)

    def save(self, global_step=0):
        tfe.Saver(self.variables).save(self.checkpoint_directory, global_step=global_step)


def main():
    import glob
    import h5py

    num_data = 2

    X = list()
    y = list()
    seq = list()

    for i in range(num_data):
        fname = "data_lmfe/data_%d.h5" % i
        h5f = h5py.File(fname, 'r')
        X.append(h5f['speechs'][:].astype(np.float32))
        y += h5f['labels'][:].tolist()
        seq += h5f['seqs'][:].tolist()
        h5f.close()

    X = np.concatenate(X, axis=0)
    y = np.array(y)
    seq = np.array(seq) / 100

    print X.shape, y.shape, seq.shape

    X_5 = list()
    for i in range(5):
        X_5.append(X[:, i * 100:i * 100 + 98, :])
    X = np.array(X_5)
    X = X.swapaxes(0, 1)
    X = X.reshape(-1, 5, 98 * 40)

    num_classes = 10 * num_data
    num_train = len(X)

    from sklearn.model_selection import train_test_split

    X_train, X_test, y_train, y_test, seq_train, seq_test = train_test_split(X, y, seq, test_size=0.33, random_state=42)
    del X, y, seq
    import gc
    gc.collect()
    ds_train = tf.data.Dataset.from_tensor_slices((X_train, y_train, seq_train)).shuffle(buffer_size=num_train).batch(128)
    ds_test = tf.data.Dataset.from_tensor_slices((X_test, y_test, seq_test)).shuffle(buffer_size=num_train).batch(128)

    model = DVectorNet((98 * 40,), num_classes, "checkpoints/", device_name="gpu:0")

    model.fit(ds_train, ds_test, epochs=100000, verbose=50)


if __name__ == "__main__":
    main()