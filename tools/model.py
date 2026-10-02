"""Modèle appris du suiveur de galeries, partagé par train.py (apprentissage) et trace.py (inférence).

Entrée  : fenêtre W×W à 4 canaux — RGB de la carte tournée « cap vers le haut » + canal « déjà tracé » (0/255).
Sortie  : K logits, un par secteur angulaire (secteur 0 = devant, horaire) ; sigmoïde → probabilité indépendante
          par direction. Plusieurs secteurs actifs = intersection ; aucun = cul-de-sac.
Réseau  : ResNet-18 pré-entraîné ImageNet, première convolution élargie à 4 canaux (le 4ᵉ initialisé par la moyenne
          des poids RGB), couche finale remplacée par une linéaire K sorties. Tout le réseau est entraîné.
"""
import numpy as np
import torch
import torch.nn as nn
import torchvision

MEAN = (0.485, 0.456, 0.406, 0.0)
STD = (0.229, 0.224, 0.225, 1.0)
ARCH = 'resnet18-4ch'


def build_net(K, pretrained=True):
    weights = torchvision.models.ResNet18_Weights.IMAGENET1K_V1 if pretrained else None
    net = torchvision.models.resnet18(weights=weights)
    old = net.conv1
    conv = nn.Conv2d(4, old.out_channels, old.kernel_size, old.stride, old.padding, bias=False)
    with torch.no_grad():
        conv.weight[:, :3] = old.weight
        conv.weight[:, 3:] = old.weight.mean(1, keepdim=True)
    net.conv1 = conv
    net.fc = nn.Linear(net.fc.in_features, K)
    return net


def to_tensor(crop, traced):
    """(PIL RGB W×W, PIL L W×W) → tenseur uint8 4×W×W."""
    a = np.concatenate([np.asarray(crop.convert('RGB')), np.asarray(traced.convert('L'))[..., None]], axis=2)
    return torch.from_numpy(np.ascontiguousarray(a)).permute(2, 0, 1).contiguous()


def normalize(x):
    """uint8 B×4×W×W → float normalisé."""
    x = x.float() / 255.0
    m = torch.tensor(MEAN, device=x.device).view(1, 4, 1, 1)
    s = torch.tensor(STD, device=x.device).view(1, 4, 1, 1)
    return (x - m) / s


def mirror_label(lab, K):
    """Étiquette du même état vu dans un miroir (fenêtre retournée gauche↔droite) : secteur k ↔ (K−k) mod K."""
    idx = (K - torch.arange(K, device=lab.device)) % K
    return lab[..., idx]


def save_checkpoint(path, net, meta):
    torch.save({'arch': ARCH, 'meta': meta, 'model': net.state_dict()}, path)


def load_checkpoint(path, device='cpu'):
    ck = torch.load(path, map_location=device, weights_only=False)
    if ck.get('arch') != ARCH:
        raise ValueError(f"architecture inattendue : {ck.get('arch')}")
    net = build_net(ck['meta']['sectors'], pretrained=False)
    net.load_state_dict(ck['model'])
    return net.to(device).eval(), ck['meta']


def pick_device(name=None):
    if name:
        return torch.device(name)
    return torch.device('cuda' if torch.cuda.is_available() else 'cpu')


class LearnedModel:
    """Interface attendue par trace.Tracer : predict(x, y, cap, (crop, traced)) → K probabilités."""
    needs_image = True

    def __init__(self, path, device=None):
        self.device = pick_device(device)
        self.net, self.meta = load_checkpoint(path, self.device)
        self.K = self.meta['sectors']

    @torch.no_grad()
    def predict(self, x, y, heading, crops):
        crop, traced = crops
        t = normalize(to_tensor(crop, traced)[None].to(self.device))
        return torch.sigmoid(self.net(t))[0].tolist()
