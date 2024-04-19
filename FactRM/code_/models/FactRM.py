from transformers import BertModel

from .coattention import *
from .layers import *

class FactRMModel(torch.nn.Module):
    def __init__(self, bert_model, fea_dim, dropout):
        super(FactRMModel, self).__init__()
        print('loading bert model from:', bert_model)
        self.bert = BertModel.from_pretrained('/root/autodl-tmp/fakesv/bert-base-chinese').requires_grad_(False)
        print('loading bert model done')

        self.text_dim = 768
        self.comment_dim = 768
        self.img_dim = 4096
        self.video_dim = 4096
        self.num_frames = 83
        self.num_audioframes = 50
        self.num_comments = 23
        self.dim = fea_dim
        self.num_heads = 4

        self.dropout = dropout

        self.attention = Attention(dim=self.dim, heads=4, dropout=dropout)
        print('add vggish!!')
        self.vggish_layer = torch.hub.load('/root/autodl-tmp/fakesv/code_/vggish', 'vggish', source='local')
        net_structure = list(self.vggish_layer.children())
        self.vggish_modified = nn.Sequential(*net_structure[-2:-1])

        self.co_attention_ta = co_attention(d_k=fea_dim, d_v=fea_dim, n_heads=self.num_heads, dropout=self.dropout,
                                            d_model=fea_dim,
                                            visual_len=self.num_audioframes, sen_len=512, fea_v=self.dim,
                                            fea_s=self.dim, pos=False)
        self.co_attention_tv = co_attention(d_k=fea_dim, d_v=fea_dim, n_heads=self.num_heads, dropout=self.dropout,
                                            d_model=fea_dim,
                                            visual_len=self.num_frames, sen_len=512, fea_v=self.dim, fea_s=self.dim,
                                            pos=False)
        self.trm = nn.TransformerEncoderLayer(d_model=self.dim, nhead=2, batch_first=True)

        self.linear_text = nn.Sequential(torch.nn.Linear(self.text_dim, fea_dim), torch.nn.ReLU(),
                                         nn.Dropout(p=self.dropout))
        self.linear_comment = nn.Sequential(torch.nn.Linear(self.comment_dim, fea_dim), torch.nn.ReLU(),
                                            nn.Dropout(p=self.dropout))
        self.linear_img = nn.Sequential(torch.nn.Linear(self.img_dim, fea_dim), torch.nn.ReLU(),
                                        nn.Dropout(p=self.dropout))
        self.linear_video = nn.Sequential(torch.nn.Linear(self.video_dim, fea_dim), torch.nn.ReLU(),
                                          nn.Dropout(p=self.dropout))
        self.linear_intro = nn.Sequential(torch.nn.Linear(self.text_dim, fea_dim), torch.nn.ReLU(),
                                          nn.Dropout(p=self.dropout))
        self.linear_audio = nn.Sequential(torch.nn.Linear(fea_dim, fea_dim), torch.nn.ReLU(),
                                          nn.Dropout(p=self.dropout))

        self.classifier = nn.Linear(fea_dim, 2)

    def forward(self, **kwargs):
        # Title
        title_input_id = kwargs['title_input_id']  # (batch,512)
        title_mask = kwargs['title_mask']  # (batch,512)

        fea_text = self.bert(title_input_id, attention_mask=title_mask)['last_hidden_state']  # (batch,sequence,768)
        fea_text = self.linear_text(fea_text)

        # Audio Frames
        audioframes = kwargs['vggish_feature']  # (batch,36,12288)
        fea_audio = self.vggish_modified(audioframes)  # (batch, frames, 128)
        fea_audio = self.linear_audio(fea_audio)
        fea_audio, fea_text = self.co_attention_ta(v=fea_audio, s=fea_text, v_len=fea_audio.shape[1],
                                                   s_len=fea_text.shape[1])
        fea_audio = torch.mean(fea_audio, -2)

        # Image Frames
        frames = kwargs['resnet50_feature']  # (batch,30,4096)
        fea_img = self.linear_img(frames)
        fea_img, fea_text = self.co_attention_tv(v=fea_img, s=fea_text, v_len=fea_img.shape[1], s_len=fea_text.shape[1])
        fea_img = torch.mean(fea_img, -2)

        fea_text = torch.mean(fea_text, -2)

        # Comment
        comments_inputid = kwargs['comments_inputid']  # (batch,20,250)
        comments_mask = kwargs['comments_mask']  # (batch,20,250)

        comments_like = kwargs['comments_like']
        comments_feature = []
        for i in range(comments_inputid.shape[0]):
            bert_fea = self.bert(comments_inputid[i], attention_mask=comments_mask[i])[1]
            comments_feature.append(bert_fea)
        comments_feature = torch.stack(comments_feature)  # (batch,seq,fea_dim)

        fea_comments = []
        for v in range(comments_like.shape[0]):
            comments_weight = torch.stack(
                [torch.true_divide((i + 1), (comments_like[v].shape[0] + comments_like[v].sum())) for i in
                 comments_like[v]])
            comments_fea_reweight = torch.sum(
                comments_feature[v] * (comments_weight.reshape(comments_weight.shape[0], 1)), dim=0)
            fea_comments.append(comments_fea_reweight)
        fea_comments = torch.stack(fea_comments)
        fea_comments = self.linear_comment(fea_comments)  # (batch,fea_dim)

        fea_text = fea_text.unsqueeze(1)
        fea_comments = fea_comments.unsqueeze(1)
        fea_img = fea_img.unsqueeze(1)
        fea_audio = fea_audio.unsqueeze(1)

        fea = torch.cat((fea_text,fea_audio,fea_img, fea_comments), 1)  # (bs, 6, 128)
        fea = self.trm(fea)
        fea = torch.mean(fea, -2)

        output = self.classifier(fea)

        return output, fea


