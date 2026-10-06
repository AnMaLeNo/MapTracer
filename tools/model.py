"""Modèle appris du suiveur de galeries, partagé par train.py (apprentissage) et trace.py (inférence).

Entrée  : fenêtre W×W à 4 canaux — RGB de la carte tournée « cap vers le haut » + canal « déjà tracé » (0/255).
Sortie  : K logits, un par secteur angulaire (secteur 0 = devant, horaire) ; sigmoïde → probabilité indépendante
          par direction. Plusieurs secteurs actifs = intersection ; aucun = cul-de-sac.
Réseau  : ResNet-18 pré-entraîné ImageNet, première convolution élargie à 4 canaux (le 4ᵉ initialisé par la moyenne
          des poids RGB), couche finale remplacée par une linéaire K sorties. Tout le réseau est entraîné.
"""
import contextlib, functools, threading

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


@functools.cache
def _mean_std(device):
    """Constantes de normalisation, créées une fois par appareil (sinon deux copies hôte → GPU à chaque inférence,
    qui dominent le temps d'un lot de 1 sur MPS)."""
    return torch.tensor(MEAN, device=device).view(1, 4, 1, 1), torch.tensor(STD, device=device).view(1, 4, 1, 1)


def normalize(x):
    """uint8 B×4×W×W → float normalisé."""
    m, s = _mean_std(x.device)
    return (x.float() / 255.0 - m) / s


def mirror_label(lab, K):
    """Étiquette du même état vu dans un miroir (fenêtre retournée gauche↔droite) : secteur k ↔ (K−k) mod K."""
    idx = (K - torch.arange(K, device=lab.device)) % K
    return lab[..., idx]


def save_checkpoint(path, net, meta, half=False):
    sd = net.state_dict()
    if half:                                   # poids en float16 (moitié moins lourd dans le dépôt) ; rechargés en float32
        sd = {k: v.half() if v.is_floating_point() else v for k, v in sd.items()}
    torch.save({'arch': ARCH, 'meta': meta, 'model': sd}, path)


def load_checkpoint(path, device='cpu'):
    ck = torch.load(path, map_location='cpu', weights_only=False)        # float16 → float32 sur CPU, puis vers l'appareil
    if ck.get('arch') != ARCH:
        raise ValueError(f"architecture inattendue : {ck.get('arch')}")
    net = build_net(ck['meta']['sectors'], pretrained=False)
    net.load_state_dict({k: v.float() if v.is_floating_point() else v for k, v in ck['model'].items()})
    return net.to(device).eval(), ck['meta']


def pick_device(name=None):
    """--device explicite, sinon le meilleur disponible : cuda (NVIDIA), mps (GPU des puces Apple M1…M5), cpu."""
    if name:
        return torch.device(name)
    if torch.cuda.is_available():
        return torch.device('cuda')
    if torch.backends.mps.is_available():
        return torch.device('mps')
    return torch.device('cpu')


class LearnedModel:
    """Interface attendue par trace.Tracer : predict(x, y, cap, (crop, traced)) → K probabilités."""
    needs_image = True

    def __init__(self, path, device=None):
        self.device = pick_device(device)
        self.net, self.meta = load_checkpoint(path, self.device)
        self.K = self.meta['sectors']
        # Le serveur appelle le réseau depuis plusieurs fils (mode Auto, audit, /api/predict) : CUDA et le CPU le
        # supportent, MPS non (plantage Metal sur des passes concurrentes) → passes sérialisées sur MPS seulement.
        self.lock = threading.Lock() if self.device.type == 'mps' else contextlib.nullcontext()
        # Sur puce Apple, un lot de 1 (mode Auto, mode assisté : un pas après l'autre) est plus lent sur MPS que sur le
        # CPU (~6 ms contre ~4 : le GPU se rendort entre deux pas) ; les lots (audit) y sont ~10× plus rapides.
        # → copie CPU du réseau pour les états isolés. Sur CUDA, tout reste sur le GPU.
        self.net_single = self.net
        if self.device.type == 'mps':
            self.net_single = load_checkpoint(path, 'cpu')[0]

    @torch.no_grad()
    def probs(self, x):
        """uint8 B×4×W×W (sur CPU) → B listes de K probabilités."""
        if len(x) == 1 and self.net_single is not self.net:
            return torch.sigmoid(self.net_single(normalize(x))).tolist()
        with self.lock:
            return torch.sigmoid(self.net(normalize(x.to(self.device)))).cpu().tolist()

    def predict(self, x, y, heading, crops):
        crop, traced = crops
        return self.probs(to_tensor(crop, traced)[None])[0]


if __name__ == '__main__':                     # python3 tools/model.py runs/x/model.pt models/x/model.pt [--half]
    import sys
    src, dst = sys.argv[1], sys.argv[2]
    net, meta = load_checkpoint(src)
    save_checkpoint(dst, net, meta, half='--half' in sys.argv)
    print(f'{dst} : {meta["sectors"]} secteurs, fenêtre {meta["window"]}, pas {meta["step"]}, ép. {meta.get("epoch")}')
