"""API-format ComfyUI workflow graphs: Flux-dev keyframe (optional LoRA), Wan 2.2 image-to-video,
ACE-Step music. Model file + decode strategy adapt to the hardware tier in config."""
import config

FLUX_UNET   = "flux1-dev.safetensors"
FLUX_T5     = "t5xxl_fp8_e4m3fn.safetensors"
FLUX_CLIPL  = "clip_l.safetensors"
FLUX_VAE    = "ae.safetensors"
# Wan model file per tier (5B for most GPUs; 14B for 24GB+ "ultra")
WAN_FILES = {
    "wan2.2_ti2v_5B":  "wan2.2_ti2v_5B_fp16.safetensors",
    "wan2.2_t2v_A14B": "wan2.2_t2v_A14B_fp8_scaled.safetensors",
}
WAN_UNET    = WAN_FILES.get(config.WAN_MODEL, "wan2.2_ti2v_5B_fp16.safetensors")
WAN_CLIP    = "umt5_xxl_fp8_e4m3fn_scaled.safetensors"
WAN_VAE     = "wan2.2_vae.safetensors"
ACE_CKPT    = "ace_step_v1_3.5b.safetensors"

def flux_keyframe(positive, negative, seed, prefix, lora=None, lora_strength=0.85,
                  steps=24, guidance=3.5, w=None, h=None):
    w = w or config.KEY_W; h = h or config.KEY_H
    g = {
        "10": {"class_type":"UNETLoader","inputs":{"unet_name":FLUX_UNET,"weight_dtype":config.FLUX_DTYPE}},
        "11": {"class_type":"DualCLIPLoader","inputs":{"clip_name1":FLUX_T5,"clip_name2":FLUX_CLIPL,"type":"flux"}},
        "12": {"class_type":"VAELoader","inputs":{"vae_name":FLUX_VAE}},
        "13": {"class_type":"CLIPTextEncode","inputs":{"text":positive,"clip":["11",0]}},
        "14": {"class_type":"FluxGuidance","inputs":{"conditioning":["13",0],"guidance":guidance}},
        "15": {"class_type":"CLIPTextEncode","inputs":{"text":negative,"clip":["11",0]}},
        "16": {"class_type":"EmptySD3LatentImage","inputs":{"width":w,"height":h,"batch_size":1}},
        "17": {"class_type":"KSampler","inputs":{"model":["10",0],"positive":["14",0],"negative":["15",0],
                "latent_image":["16",0],"seed":seed,"steps":steps,"cfg":1.0,
                "sampler_name":"euler","scheduler":"simple","denoise":1.0}},
        "18": {"class_type":"VAEDecode","inputs":{"samples":["17",0],"vae":["12",0]}},
        "19": {"class_type":"SaveImage","inputs":{"images":["18",0],"filename_prefix":prefix}},
    }
    if lora:
        g["20"] = {"class_type":"LoraLoaderModelOnly",
                   "inputs":{"model":["10",0],"lora_name":lora,"strength_model":lora_strength}}
        g["17"]["inputs"]["model"] = ["20",0]
    return g

def ace_step(tags, lyrics, seconds, seed, prefix, steps=50, cfg=5.0):
    return {
        "1": {"class_type":"CheckpointLoaderSimple","inputs":{"ckpt_name":ACE_CKPT}},
        "2": {"class_type":"TextEncodeAceStepAudio","inputs":{"tags":tags,"lyrics":lyrics,
                "lyrics_strength":0.99,"clip":["1",1]}},
        "3": {"class_type":"ConditioningZeroOut","inputs":{"conditioning":["2",0]}},
        "4": {"class_type":"EmptyAceStepLatentAudio","inputs":{"seconds":seconds,"batch_size":1}},
        "5": {"class_type":"KSampler","inputs":{"model":["1",0],"positive":["2",0],"negative":["3",0],
                "latent_image":["4",0],"seed":seed,"steps":steps,"cfg":cfg,
                "sampler_name":"euler","scheduler":"simple","denoise":1.0}},
        "6": {"class_type":"VAEDecodeAudio","inputs":{"samples":["5",0],"vae":["1",2]}},
        "7": {"class_type":"SaveAudio","inputs":{"audio":["6",0],"filename_prefix":prefix}},
    }

def wan_i2v(motion_positive, negative, start_image_name, seed, prefix,
            steps=None, cfg=4.0, length=None, w=None, h=None, shift=5.0):
    w = w or config.WAN_W; h = h or config.WAN_H
    length = length or config.WAN_FRAMES
    steps = steps or config.WAN_STEPS
    # tiled VAE decode on lower-VRAM tiers (prevents OOM crash); full decode on 24GB+ ultra
    if config.WAN_TILED:
        decode = {"class_type":"VAEDecodeTiled","inputs":{"samples":["37",0],"vae":["32",0],
                  "tile_size":256,"overlap":64,"temporal_size":32,"temporal_overlap":8}}
    else:
        decode = {"class_type":"VAEDecode","inputs":{"samples":["37",0],"vae":["32",0]}}
    return {
        "30": {"class_type":"UNETLoader","inputs":{"unet_name":WAN_UNET,"weight_dtype":config.WAN_DTYPE}},
        "31": {"class_type":"CLIPLoader","inputs":{"clip_name":WAN_CLIP,"type":"wan"}},
        "32": {"class_type":"VAELoader","inputs":{"vae_name":WAN_VAE}},
        "33": {"class_type":"LoadImage","inputs":{"image":start_image_name}},
        "34": {"class_type":"CLIPTextEncode","inputs":{"text":motion_positive,"clip":["31",0]}},
        "35": {"class_type":"CLIPTextEncode","inputs":{"text":negative,"clip":["31",0]}},
        "36": {"class_type":"WanImageToVideo","inputs":{"positive":["34",0],"negative":["35",0],
                "vae":["32",0],"width":w,"height":h,"length":length,"batch_size":1,"start_image":["33",0]}},
        "40": {"class_type":"ModelSamplingSD3","inputs":{"model":["30",0],"shift":shift}},
        "37": {"class_type":"KSampler","inputs":{"model":["40",0],"positive":["36",0],"negative":["36",1],
                "latent_image":["36",2],"seed":seed,"steps":steps,"cfg":cfg,
                "sampler_name":"uni_pc","scheduler":"simple","denoise":1.0}},
        "38": decode,
        "39": {"class_type":"SaveImage","inputs":{"images":["38",0],"filename_prefix":prefix}},
    }
