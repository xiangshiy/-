import copy
import os
import time

import tqdm
from sklearn.metrics import accuracy_score
from tqdm import tqdm
from zmq import device

from .layers import *
from utils.metrics import metrics, get_confusionmatrix_fnd


class Trainer():
    def __init__(self,
                 model,
                 device,
                 lr,
                 dropout,
                 dataloaders,
                 weight_decay,
                 save_param_path,
                 writer,
                 epoch_stop,
                 epoches,
                 mode,
                 model_name,
                 event_num,
                 save_threshold=0.0,
                 start_epoch=0,
                 ):

        self.optimizer = None
        self.model = model
        self.device = device
        self.mode = mode
        self.model_name = model_name
        self.event_num = event_num

        self.dataloaders = dataloaders
        self.start_epoch = start_epoch
        self.num_epochs = epoches
        self.epoch_stop = epoch_stop
        self.save_threshold = save_threshold
        self.writer = writer

        if os.path.exists(save_param_path):
            self.save_param_path = save_param_path
        else:
            self.save_param_path = os.makedirs(save_param_path)
            self.save_param_path = save_param_path

        self.lr = lr
        self.weight_decay = weight_decay
        self.dropout = dropout

        self.criterion = nn.CrossEntropyLoss()

    def train(self):

        since = time.time()

        self.model.cuda()

        best_model_wts_test = copy.deepcopy(self.model.state_dict())
        best_acc_test = 0.0
        best_epoch_test = 0
        is_earlystop = False

        for epoch in range(self.start_epoch, self.start_epoch + self.num_epochs):
            if is_earlystop:
                break
            print('-' * 50)
            print('Epoch {}/{}'.format(epoch + 1, self.start_epoch + self.num_epochs))
            print('-' * 50)

            p = float(epoch) / 100
            lr = self.lr / (1. + 10 * p) ** 0.75
            self.optimizer = torch.optim.Adam(params=self.model.parameters(), lr=lr)

            for phase in ['train', 'test']:
                if phase == 'train':
                    self.model.train()
                else:
                    self.model.eval()
                print('-' * 10)
                print(phase.upper())
                print('-' * 10)

                running_loss_fnd = 0.0
                running_loss = 0.0
                tpred = []
                tlabel = []

                for batch in tqdm(self.dataloaders[phase]):
                    batch_data = batch
                    if batch_data is None:
                        continue
                    for k, v in batch_data.items():
                        batch_data[k] = v.cuda()
                    label = batch_data['label']

                    with torch.set_grad_enabled(phase == 'train'):
                        outputs, fea = self.model(**batch_data)
                        _, preds = torch.max(outputs, 1)
                        loss = self.criterion(outputs, label)

                        if phase == 'train':
                            loss.backward()
                            self.optimizer.step()
                            self.optimizer.zero_grad()

                    tlabel.extend(label.detach().cpu().numpy().tolist())
                    tpred.extend(preds.detach().cpu().numpy().tolist())
                    running_loss += loss.item() * label.size(0)

                epoch_loss = running_loss / len(self.dataloaders[phase].dataset)
                print('Loss: {:.4f} '.format(epoch_loss))
                results = metrics(tlabel, tpred)
                print("Trainer:120",results)

                if phase == 'test':
                    if results['acc'] > best_acc_test:
                        best_acc_test = results['acc']
                        best_model_wts_test = copy.deepcopy(self.model.state_dict())
                        best_epoch_test = epoch + 1
                        if best_acc_test > self.save_threshold:
                            torch.save(self.model.state_dict(),
                                       self.save_param_path + "_test_epoch" + str(best_epoch_test) + "_{0:.4f}".format(
                                           best_acc_test))
                            print("saved " + self.save_param_path + "_test_epoch" + str(
                                best_epoch_test) + "_{0:.4f}".format(best_acc_test))
                    else:
                        if epoch - best_epoch_test >= self.epoch_stop - 1:
                            is_earlystop = True
                            print("early stopping...")

        time_elapsed = time.time() - since
        print('Training complete in {:.0f}m {:.0f}s'.format(
            time_elapsed // 60, time_elapsed % 60))
        print("Best model on test: epoch" + str(best_epoch_test) + "_" + str(best_acc_test))

        self.model.load_state_dict(best_model_wts_test)
        return self.test()

    def test(self):
        since = time.time()

        self.model.cuda()
        self.model.eval()

        pred = []
        label = []

        if self.mode == "eann":
            pred_event = []
            label_event = []

        for batch in tqdm(self.dataloaders['test']):
            with torch.no_grad():
                batch_data = batch
                for k, v in batch_data.items():
                    batch_data[k] = v.cuda()
                batch_label = batch_data['label']

                if self.mode == "eann":
                    batch_label_event = batch_data['label_event']
                    batch_outputs, batch_outputs_event, fea = self.model(**batch_data)
                    _, batch_preds_event = torch.max(batch_outputs_event, 1)

                    label_event.extend(batch_label_event.detach().cpu().numpy().tolist())
                    pred_event.extend(batch_preds_event.detach().cpu().numpy().tolist())
                else:
                    batch_outputs, fea = self.model(**batch_data)

                _, batch_preds = torch.max(batch_outputs, 1)

                label.extend(batch_label.detach().cpu().numpy().tolist())
                pred.extend(batch_preds.detach().cpu().numpy().tolist())

        print(get_confusionmatrix_fnd(np.array(pred), np.array(label)))
        print(metrics(label, pred))

        if self.mode == "eann" and self.model_name != "FANVM":
            print("event:")
            print(accuracy_score(np.array(label_event), np.array(pred_event)))

        return metrics(label, pred)
