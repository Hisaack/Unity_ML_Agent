# 라이브러리 불러오기
import numpy as np
import random
import datetime
import time
import tensorflow as tf
from collections import deque
from mlagents.envs import UnityEnvironment

# DQN을 위한 파라미터 값 세팅 
state_size = [80, 80, 1]
action_size = 3

load_model = False
train_mode = True

batch_size = 32
mem_maxlen = 50000
discount_factor = 0.99
learning_rate = 0.00025

skip_frame = 5
stack_frame = 4

run_episode = 2500
test_episode = 100

start_train_episode = 100

target_update_step = 10000
print_interval = 25
save_interval = 5000

epsilon_init = 1.0
epsilon_min = 0.1

date_time = datetime.datetime.now().strftime("%Y%m%d-%H-%M-%S")

# 유니티 환경 경로 
game = "VehicleDynamicObs"
env_name = "../env/" + game + "/Windows/" + game

# 모델 저장 및 불러오기 경로
save_path = "../saved_models/" + game + "/" + date_time + "_NoisyNet"
load_path = "../saved_models/" + game + "/20190828-10-42-45_NoisyNet/model/model"

# Model 클래스 -> 함성곱 신경망 정의 및 손실함수 설정, 네트워크 최적화 알고리즘 결정
class Model():
    def __init__(self, model_name):
        self.input = tf.placeholder(shape=[None, state_size[0], state_size[1], 
                                           state_size[2]*stack_frame], dtype=tf.float32)
        # 입력을 -1 ~ 1까지 값을 가지도록 정규화
        self.input_normalize = (self.input - (255.0 / 2)) / (255.0 / 2)

        # CNN Network 구축 -> 3개의 Convolutional layer와 2개의 Fully connected layer
        with tf.variable_scope(name_or_scope=model_name):
            self.conv1 = tf.layers.conv2d(inputs=self.input_normalize, filters=32, 
                                            activation=tf.nn.relu, kernel_size=[8,8], 
                                            strides=[4,4], padding="SAME")
            self.conv2 = tf.layers.conv2d(inputs=self.conv1, filters=64, 
                                            activation=tf.nn.relu, kernel_size=[4,4],
                                            strides=[2,2],padding="SAME")
            self.conv3 = tf.layers.conv2d(inputs=self.conv2, filters=64, 
                                            activation=tf.nn.relu, kernel_size=[3,3],
                                            strides=[1,1],padding="SAME")

            self.flat = tf.layers.flatten(self.conv3)

            ########################################### Noisy Network ###########################################
            # 학습 여부 bool 형태로 받아오기 
            self.is_train = tf.placeholder(tf.bool)

            self.fc1 = tf.nn.relu(self.noisy_dense(self.flat, [self.flat.shape[1], 512], self.is_train))
            self.Q_Out = self.noisy_dense(self.fc1, [512, action_size], self.is_train)
            #####################################################################################################

        self.predict = tf.argmax(self.Q_Out, 1)

        self.target_Q = tf.placeholder(shape=[None, action_size], dtype=tf.float32)

        # 손실함수 값 계산 및 네트워크 학습 수행 
        self.loss = tf.losses.huber_loss(self.target_Q, self.Q_Out)
        self.UpdateModel = tf.train.AdamOptimizer(learning_rate).minimize(self.loss)
        self.trainable_var = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, model_name)

    ########################################### Noisy Network ###########################################
    def mu_variable(self, shape):
        return tf.Variable(tf.random_uniform(shape, minval = -tf.sqrt(3/shape[0]), maxval = tf.sqrt(3/shape[0])))

    def sigma_variable(self, shape):
        return tf.Variable(tf.constant(0.017, shape = shape))

    def noisy_dense(self, input_, input_shape, is_train):
        # NoisyNet 변수 정의
        mu_w  = self.mu_variable(input_shape)
        sig_w = self.sigma_variable(input_shape)
        mu_b  = self.mu_variable([input_shape[1]])
        sig_b = self.sigma_variable([input_shape[1]])

        # 변수들에 대한 Epsilon 계산
        eps_w = tf.cond(is_train, lambda: tf.random_normal(input_shape), lambda: tf.zeros(input_shape))
        eps_b = tf.cond(is_train, lambda: tf.random_normal([input_shape[1]]), lambda: tf.zeros([input_shape[1]]))

        # FC 연산 수행 
        w_fc = tf.add(mu_w, tf.multiply(sig_w, eps_w))
        b_fc = tf.add(mu_b, tf.multiply(sig_b, eps_b))

        return tf.matmul(input_, w_fc) + b_fc
    #####################################################################################################

# DQNAgent 클래스 -> DQN 알고리즘을 위한 다양한 함수 정의 
class DQNAgent():
    def __init__(self):
        
        # 클래스의 함수들을 위한 값 설정 
        self.model = Model("Q")
        self.target_model = Model("target")

        self.memory = deque(maxlen=mem_maxlen)
        self.obs_set = deque(maxlen=skip_frame*stack_frame)

        self.sess = tf.Session()
        self.init = tf.global_variables_initializer()
        self.sess.run(self.init)

        self.epsilon = epsilon_init

        self.Saver = tf.train.Saver()
        self.Summary, self.Merge = self.Make_Summary()

        self.update_target()

        if load_model == True:
            self.Saver.restore(self.sess, load_path)

    # Epsilon greedy 기법에 따라 행동 결정
    def get_action(self, state):
        if self.epsilon > np.random.rand():
            # 랜덤하게 행동 결정
            return np.random.randint(0, action_size)
        else:
            # 네트워크 연산에 따라 행동 결정
            predict = self.sess.run(self.model.predict, feed_dict={self.model.input: [state],
                                                                   self.model.is_train: False})
            return np.asscalar(predict)

    # 프레임을 skip하면서 설정에 맞게 stack
    def skip_stack_frame(self, step, obs):
        self.obs_set.append(obs)

        state = np.zeros([state_size[0], state_size[1], state_size[2]*stack_frame])

        # skip frame마다 한번씩 obs를 stacking
        for i in range(stack_frame):
            state[:,:, state_size[2]*i : state_size[2]*(i+1)] = self.obs_set[-1 - (skip_frame*i)]

        return np.uint8(state)

    # 리플레이 메모리에 데이터 추가 (상태, 행동, 보상, 다음 상태, 게임 종료 여부)
    def append_sample(self, state, action, reward, next_state, done):
        self.memory.append((state, action, reward, next_state, done))

    # 네트워크 모델 저장 
    def save_model(self):
        self.Saver.save(self.sess, save_path + "/model/model")

    # 학습 수행 
    def train_model(self, done):
        # Epsilon 값 감소 
        if done:
            if self.epsilon > epsilon_min:
                self.epsilon -= 1 / (run_episode - start_train_episode)

        # 학습을 위한 미니 배치 데이터 샘플링
        mini_batch = random.sample(self.memory, batch_size)

        states = []
        actions = []
        rewards = []
        next_states = []
        dones = []

        for i in range(batch_size):
            states.append(mini_batch[i][0])
            actions.append(mini_batch[i][1])
            rewards.append(mini_batch[i][2])
            next_states.append(mini_batch[i][3])
            dones.append(mini_batch[i][4])

        # 타겟값 계산 
        target = self.sess.run(self.model.Q_Out, feed_dict={self.model.input: states, self.model.is_train: True})
        target_val = self.sess.run(self.target_model.Q_Out, 
                                    feed_dict={self.target_model.input: next_states, self.model.is_train: True})

        for i in range(batch_size):
            if dones[i]:
                target[i][actions[i]] = rewards[i]
            else:
                target[i][actions[i]] = rewards[i] + discount_factor * np.amax(target_val[i])

        # 학습 수행 및 손실함수 값 계산 
        _, loss = self.sess.run([self.model.UpdateModel, self.model.loss],
                                feed_dict={self.model.input: states, 
                                           self.model.target_Q: target,
                                           self.model.is_train: True})
        return loss

    # 타겟 네트워크 업데이트 
    def update_target(self):
        for i in range(len(self.model.trainable_var)):
            self.sess.run(self.target_model.trainable_var[i].assign(self.model.trainable_var[i]))

    # 텐서보드에 기록할 값 설정 및 데이터 기록 
    def Make_Summary(self):
        self.summary_loss = tf.placeholder(dtype=tf.float32)
        self.summary_reward = tf.placeholder(dtype=tf.float32)
        tf.summary.scalar("loss", self.summary_loss)
        tf.summary.scalar("reward", self.summary_reward)
        Summary = tf.summary.FileWriter(logdir=save_path, graph=self.sess.graph)
        Merge = tf.summary.merge_all()

        return Summary, Merge

    def Write_Summray(self, reward, loss, episode):
        self.Summary.add_summary(
            self.sess.run(self.Merge, feed_dict={self.summary_loss: loss, 
                                                    self.summary_reward: reward}), episode)

# Main 함수 -> 전체적으로 DQN 알고리즘을 진행 
if __name__ == '__main__':
    # 유니티 환경 경로 설정 (file_name)
    env = UnityEnvironment(file_name=env_name)

    # 유니티 브레인 설정 
    default_brain = env.brain_names[0]
    brain = env.brains[default_brain]

    # DQNAgent 클래스를 agent로 정의 
    agent = DQNAgent()

    step = 0
    rewards = []
    losses = []

    # 유니티 환경 리셋 및 학습 모드 설정  
    env_info = env.reset(train_mode=train_mode)[default_brain]

    # 게임 진행 반복문 
    for episode in range(run_episode + test_episode):
        if episode == run_episode:
            train_mode = False
            env_info = env.reset(train_mode=train_mode)[default_brain]
        
        # 상태, episode_rewards, done 초기화 
        obs = 255 * np.array(env_info.visual_observations[0])
        episode_rewards = 0
        done = False

        for i in range(skip_frame*stack_frame):
            agent.obs_set.append(np.zeros([state_size[0], state_size[1], state_size[2]]))

        state = agent.skip_stack_frame(step, obs)

        # 한 에피소드를 진행하는 반복문 
        while not done:
            step += 1

            # 행동 결정 및 유니티 환경에 행동 적용 
            action = agent.get_action(state)
            env_info = env.step(action)[default_brain]

            # 다음 상태, 보상, 게임 종료 정보 취득 
            next_obs = 255 * np.array(env_info.visual_observations[0])
            reward = env_info.rewards[0]
            episode_rewards += reward
            done = env_info.local_done[0]

            next_state = agent.skip_stack_frame(step, next_obs)

            # 학습 모드인 경우 리플레이 메모리에 데이터 저장 
            if train_mode:
                agent.append_sample(state, action, reward, next_state, done)
            else:
                time.sleep(0.0) 
                agent.epsilon = 0.0

            # 상태 정보 업데이트 
            state = next_state

            if episode > start_train_episode and train_mode:
                # 학습 수행 
                loss = agent.train_model(done)
                losses.append(loss)

                # 타겟 네트워크 업데이트 
                if step % (target_update_step) == 0:
                    agent.update_target()

        rewards.append(episode_rewards)

        # 게임 진행 상황 출력 및 텐서 보드에 보상과 손실함수 값 기록 
        if episode % print_interval == 0 and episode != 0:
            print("step: {} / episode: {} / reward: {:.2f} / loss: {:.4f} / epsilon: {:.3f}".format
                  (step, episode, np.mean(rewards), np.mean(losses), agent.epsilon))
            agent.Write_Summray(np.mean(rewards), np.mean(losses), episode)
            rewards = []
            losses = []

        # 네트워크 모델 저장 
        if episode % save_interval == 0 and episode != 0:
            agent.save_model()
            print("Save Model {}".format(episode))

    agent.save_model()
    print("Save Model {}".format(episode))
    env.close()