"""Canonical character + style descriptions — the backbone of frame-to-frame consistency.
Every keyframe prompt = STYLE + the exact canonical string for each character in frame.
Matches the design briefs in Bernie_Show/04_Character_and_Voice_Briefs.md."""

# One global look, repeated verbatim on every shot so the model stays on-style.
STYLE = (
    "modern 3D animated preschool cartoon, Moonbug/modern-studio style, soft global illumination, "
    "rounded shapes, clean simple shading, big expressive eyes, warm storybook color palette, "
    "shallow depth of field, cinematic lighting, high detail, 16:9, no text, no watermark"
)
NEG = (
    "scary, sharp teeth, realistic, photorealistic, real fur, horror, dark, gloomy, deformed, extra limbs, "
    "bad anatomy, blurry, low quality, text, watermark, signature, ugly, creepy, two heads, duplicate, "
    "overexposed, washed out, faded, blank, empty, foggy haze"
)

# token = short tag used in shot descriptions; desc = full canonical appearance string.
CHARS = {
    "BERNIE": dict(
        desc="Bernie, a round fluffy Bernese Mountain Dog puppy, oversized paws, black fur (#2B2B2E) "
             "with a warm-white chest blaze and muzzle, rust eyebrow dots, amber eyes, floppy triangle "
             "ears, wearing a red bandana with a gold paw tag, sparkly-eyed and friendly",
        voice=("en-US-AnaNeural", "+10%", "+0Hz")),
    "PIP": dict(
        desc="Pip, a tiny cute red ladybug with four black spots, big white eyes, springy antennae, "
             "very small, expressive",
        voice=("en-US-AnaNeural", "+22%", "+16Hz")),
    "TUMBLE": dict(
        desc="Tumble, a small chubby cartoon Stegosaurus, teal-green (#3FA796) with soft-yellow back "
             "plates, rosy cheeks, gentle smiley face, swingy tail, goofy and friendly",
        voice=("en-US-EricNeural", "+2%", "-8Hz")),
    "ROSIE": dict(
        desc="Rosie, a small shy baby Triceratops, lavender-pink (#C9A0DC), three blunt cream horns, "
             "scalloped frill, green eyes, a little white-and-yellow daisy on her frill, timid",
        voice=("en-US-MichelleNeural", "-2%", "+12Hz")),
    "SKY": dict(
        desc="Sky, a sleek cartoon Pteranodon, sky-blue (#6CC4E6) with white belly, orange beak, a long "
             "crest with little goggles, confident and cool",
        voice=("en-US-JennyNeural", "+8%", "+4Hz")),
    "REX": dict(
        desc="Grandpa Rex, a big soft round elderly T-Rex, mossy-green (#6B8E5A), gray whisker-scales, "
             "rounded (never sharp) teeth, comically tiny arms, a cozy woven scarf, gentle and warm",
        voice=("en-US-ChristopherNeural", "-8%", "-12Hz")),
    "MAPLE": dict(
        desc="Maple, a kind old tortoise with a warm-brown domed shell, olive skin, half-moon gold "
             "spectacles, wise and calm",
        voice=("en-GB-RyanNeural", "-8%", "-10Hz")),
    "SEAGULL": dict(
        desc="a small white cartoon seagull",
        voice=None),
    "NARR": dict(desc="", voice=("en-US-GuyNeural", "+0%", "+0Hz")),
}

# canonical recurring locations — rich, cinematic, consistent storybook-3D environments
ENV_STYLE = ("beautifully detailed 3D environment, depth and atmosphere, soft volumetric light, "
             "lush painterly background, gentle bokeh, warm inviting storybook world")
LOCATIONS = {
    "HARBOR": "Pawford Harbor, a cozy seaside town of crooked pastel cottages with round windows, a "
        "weathered wooden dock and little fishing boats, calm turquoise water with gentle sparkling waves, "
        "soft golden morning light, distant rolling green hills, " + ENV_STYLE,
    "LIGHTHOUSE": "a charming red-and-white striped lighthouse on a grassy bluff above the sea, a shiny "
        "brass telescope, wildflowers swaying, seagulls drifting, bright cheerful sunshine, sparkling ocean "
        "horizon behind, " + ENV_STYLE,
    "CAVE": "the mossy mouth of the Whispering Cave, smooth wet rocks draped in soft green moss and tiny "
        "glowing crystals, gentle magical mist curling out, warm light glowing from deeper inside, "
        "calming and safe (never dark or scary), " + ENV_STYLE,
    "VALLEY": "Dino Valley, a breathtaking sunlit jungle valley, layered lush green trees and tropical "
        "ferns, gentle cascading waterfalls, candy-bright flowers, plate-sized butterflies, soft mist in the "
        "distance, golden god-rays through the canopy, vibrant and magical, " + ENV_STYLE,
    "DOCK_DUSK": "the Pawford dock at dusk, glowing purple-orange-pink sunset sky, calm mirror-still water "
        "reflecting the colors, the lighthouse softly blinking, first fireflies, cozy and dreamy, " + ENV_STYLE,
    # --- Episode 2 locations ---
    "GIGGLE_GROVE": "the magical Giggle Grove, a hidden sunlit clearing carpeted with glowing pastel pink "
        "and lavender giggle-flowers that twinkle and sparkle, drifting golden fireflies and floating "
        "petals, a soft rainbow shimmer in the air, enchanting and whimsical, " + ENV_STYLE,
    "SUNNY_RIVER": "a sparkling clear shallow river winding through Dino Valley, smooth round stepping "
        "stones across it, glittering sunlight dancing on ripples, darting blue dragonflies, mossy banks "
        "with reeds and flowers, cheerful and bright, " + ENV_STYLE,
    "ROSIE_HOLLOW": "a cozy secret hollow tucked under the roots of a giant friendly tree, surrounded by "
        "soft ferns and glowing mushrooms, plush mossy ground, warm dappled shafts of light filtering down, "
        "snug and safe and inviting, " + ENV_STYLE,
    "TALL_TREES": "a grove of enormous ancient trees in Dino Valley with thick mossy trunks, towering "
        "canopy with sunbeams streaming through, gentle hanging vines and glowing leaves, a sense of awe "
        "and wonder, soft floating spores in the light, " + ENV_STYLE,
    "BERRY_PATCH": "a bright cheerful berry patch on a sunny grassy hill in Dino Valley, round bushes "
        "heavy with glossy red, blue and purple berries, fluttering butterflies, fluffy clouds, a gentle "
        "breeze through the grass, " + ENV_STYLE,
}

def char_block(tokens):
    """Join the canonical descriptions for the characters present in a shot."""
    return ", ".join(CHARS[t]["desc"] for t in tokens if t in CHARS and CHARS[t]["desc"])
