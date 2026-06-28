"""Builds episode.json — the full shot list for Ep1 'Bernie Finds the Valley'.
Hand-authored from 02_Episode_1_Script.md for maximum control over staging + consistency.
Each shot -> full Flux keyframe prompt (STYLE + canonical chars + location + action),
a Wan motion prompt, dialogue lines (speaker, text), and a beat tag for music/grade."""
import json
from characters import STYLE, NEG, char_block, LOCATIONS

# shot = (id, location_key, [char tokens], action, camera_motion, [(speaker,line)], beat)
SHOTS = [
    # ---------- COLD OPEN ----------
    ("s01","HARBOR",["BERNIE","PIP"],
     "wide establishing shot of the cozy harbor at dawn, Bernie asleep curled on the end of the wooden dock, one giant paw twitching, tiny ladybug Pip snoozing in his ear fluff",
     "slow gentle push-in, soft morning light, drifting clouds", [("PIP","No… the giant cookie is MINE…")],"open"),
    ("s02","HARBOR",["BERNIE","SEAGULL"],
     "close on Bernie's sleeping face, a small white seagull lands right on his nose, Bernie's eyes pop wide open and cross-eyed in surprise",
     "quick comedic zoom on eyes popping open", [("BERNIE","Pip. Pip! There's a bird. On my face.")],"open"),
    ("s03","HARBOR",["BERNIE","PIP"],
     "Pip jolts awake and tumbles off onto Bernie's nose, arms flailing, big startled eyes",
     "snappy shake, Pip bounces", [("PIP","WHO?! WHAT?! IS IT BREAKFAST?!")],"open"),
    ("s04","HARBOR",["BERNIE"],
     "the seagull flaps away dropping a rolled-up leaf tied with seaweed, it bonks Bernie right between the eyes",
     "leaf arcs down, light bonk, Bernie blinks", [("BERNIE","Ow! …Ooh. A present?")],"open"),
    ("s05","HARBOR",["BERNIE","PIP"],
     "Pip stands proudly on the rolled leaf gesturing, Bernie leans in curious, sparkling eyes",
     "two-shot, Bernie's eyes begin to sparkle", [("PIP","That's not a present, Bernie. That's a message!"),("BERNIE","A message means… ADVENTURE!")],"open"),
    # ---------- THEME (montage, no dialogue) ----------
    ("s06","HARBOR",["BERNIE","PIP"],
     "joyful montage shot, Bernie bounding through a field of bright flowers, Pip riding his nose like a tiny captain, petals flying",
     "tracking side shot, energetic bounce, sunny", [],"theme"),
    ("s07","VALLEY",["BERNIE","PIP"],
     "Bernie splashing happily in sparkling tide pools, Pip cheering, water droplets catching the light",
     "playful low angle, splashes, slow-mo droplets", [],"theme"),
    ("s08","HARBOR",["BERNIE","PIP"],
     "title card moment, Bernie strikes a brave happy pose on a hill at sunrise, Pip on his nose",
     "heroic slow rise, lens flare", [],"theme"),
    # ---------- ACT ONE — THE MESSAGE ----------
    ("s09","LIGHTHOUSE",["MAPLE"],
     "Maple the old tortoise polishes a brass telescope outside the lighthouse, calm and content",
     "gentle establishing pan", [],"calm"),
    ("s10","LIGHTHOUSE",["BERNIE","PIP","MAPLE"],
     "Bernie skids to a stop in front of Maple, Pip on his nose, excited and breathless",
     "Bernie skids in dust puff", [("BERNIE","Maple! We got a message and I can't read it 'cause it keeps rolling and—"),("MAPLE","Slow down, young pup. A story told too fast loses its tail.")],"calm"),
    ("s11","LIGHTHOUSE",["PIP"],
     "close on Pip pacing across the unrolled leaf reading it aloud, tiny finger tracing words",
     "macro close-up, soft focus background", [("PIP","To whoever finds this… I am big, but I am lonely. Come to the valley where the sun touches the tall green trees. Follow the whispering wind. — A friend.")],"tender"),
    ("s12","LIGHTHOUSE",["BERNIE"],
     "Bernie's face goes soft and caring, ears lowered, touched by the message",
     "slow push-in on tender expression", [("BERNIE","Somebody's lonely, Pip. And nobody should feel alone.")],"tender"),
    ("s13","LIGHTHOUSE",["BERNIE","MAPLE"],
     "Maple hands Bernie a tiny compass on a string, eyes twinkling with wisdom",
     "warm two-shot, compass glints", [("MAPLE","Follow the wind to the Whispering Cave. And Bernie — being brave doesn't mean you're not scared. It means you go anyway.")],"tender"),
    # ---------- ACT TWO — INTO THE VALLEY ----------
    ("s14","CAVE",["BERNIE"],
     "Bernie stands at the mossy mouth of the Whispering Cave, knees knocking, nervous gulp, soft glowing mist inside",
     "slow ominous-but-gentle push toward dark cave", [("BERNIE","Being brave doesn't mean you're not scared. It means you go anyway.")],"brave"),
    ("s15","CAVE",["BERNIE"],
     "Bernie takes a deep breath and steps into the shimmering cave, a magical light shimmer washes over him",
     "push through into bright shimmer transition", [],"brave"),
    ("s16","VALLEY",["BERNIE"],
     "reveal of breathtaking Dino Valley, lush sunlit jungle, waterfalls, candy-bright flowers, a plate-sized butterfly floats past, Bernie's tail wagging so hard his back wiggles, awestruck",
     "epic slow reveal pan across the valley", [],"wonder"),
    ("s17","VALLEY",["BERNIE","PIP"],
     "Bernie and Pip gazing up in wonder at the tall sunlit trees",
     "low hero angle looking up", [("PIP","Bernie… the sun is touching the trees."),("BERNIE","We found it!")],"wonder"),
    ("s18","VALLEY",["BERNIE","PIP"],
     "a loud rustle in the ferns, Bernie freezes mid-step, Pip dives into the ear fluff, suspense",
     "quick freeze, ferns shake", [],"suspense"),
    ("s19","VALLEY",["BERNIE"],
     "Bernie trembling but standing his ground bravely facing the rustling ferns",
     "handheld nervous framing", [("BERNIE","H-hello? We got your message! We're… we're friendly!")],"suspense"),
    ("s20","VALLEY",["BERNIE","TUMBLE"],
     "the ferns part and out tumbles Tumble the goofy young Stegosaurus, tail swinging and bonking a tree, a coconut drops and Bernie catches it in his mouth",
     "comedic reveal, coconut bonk, Bernie catch", [("TUMBLE","WHOOPS — comin' through! Sorry, tree! Oh — HI! New friend?!")],"reveal"),
    ("s21","VALLEY",["TUMBLE"],
     "Tumble's happy face deflates into shy worry, scuffing one foot",
     "push-in as expression deflates", [("TUMBLE","I LOVE new friends! …Wait. You're not scared of me?")],"reveal"),
    # ---------- ACT THREE — PROBLEM & STUMBLE ----------
    ("s22","VALLEY",["BERNIE","TUMBLE"],
     "Bernie smiles warmly and shakes his head, reassuring Tumble",
     "warm two-shot", [("BERNIE","Scared? No way! I'm Bernie. Did you send the message? About being lonely?")],"warm"),
    ("s23","VALLEY",["TUMBLE"],
     "Tumble scuffing his foot, sad and lonely, looking down",
     "soft low push-in", [("TUMBLE","Yeah. Everybody runs away when they see my big plates and my bonky tail. So nobody ever stays to say hi.")],"sad"),
    ("s24","VALLEY",["BERNIE","TUMBLE"],
     "Bernie offers a friendly paw-shake but Tumble's nervous tail swings and knocks Bernie into a leafy bush",
     "comedic swing, Bernie flies into bush", [],"sad"),
    ("s25","VALLEY",["BERNIE","TUMBLE"],
     "Bernie pops out of the bush with leaves on his head, smiling kindly, Tumble gasps miserably",
     "Bernie pops up, leaves fall", [("TUMBLE","See? I ruin everything.")],"sad"),
    ("s26","VALLEY",["BERNIE","PIP"],
     "close on Bernie gently picking leaves off his head, a thoughtful kind realization on his face, Pip beside him",
     "intimate close-up", [("BERNIE","Pip, he's not scary. He's scared. Same as I was at the cave."),("PIP","Spot-on, buddy.")],"tender"),
    # ---------- SONG: SAY HELLO ----------
    ("s27","VALLEY",["BERNIE","TUMBLE"],
     "soft musical moment, Bernie walks slowly around to face Tumble with an encouraging smile, gentle golden light",
     "graceful arc around, warm glow", [],"song"),
    ("s28","VALLEY",["BERNIE","TUMBLE","PIP"],
     "heartwarming song staging, Bernie singing gently to Tumble who begins to smile, Pip swaying on Bernie's nose, sparkles in the air",
     "gentle sway, light particles, dreamy", [],"song"),
    ("s29","VALLEY",["BERNIE","TUMBLE"],
     "Tumble swaying and smiling, fully cheered up, glowing with happiness as the song lifts",
     "uplift crane up, brighter light", [],"song"),
    # ---------- ACT FOUR — TEAMWORK & FACT ----------
    ("s30","VALLEY",["SKY"],
     "Sky the cool Pteranodon swoops down and lands on a rock with a confident grin",
     "dynamic swoop-in landing", [("SKY","Did somebody finally stay and say hi to Tumble? About time, fuzzy!")],"arrive"),
    ("s31","VALLEY",["ROSIE"],
     "Rosie the tiny shy Triceratops peeks out from behind a fern, timid little wave",
     "slow reveal from behind fern", [("ROSIE","H-hello…")],"arrive"),
    ("s32","VALLEY",["REX","BERNIE"],
     "Grandpa Rex the big gentle T-Rex rumbles up warm and slow, leaning down kindly to Bernie",
     "low awe angle, gentle giant approach", [("REX","You see, little one? You can't know somebody's heart till you say hello.")],"arrive"),
    ("s33","VALLEY",["BERNIE","TUMBLE"],
     "Tumble's tail swings happily, Bernie ducks then leaps and catches the falling coconut again, everyone delighted",
     "playful action, coconut catch", [("BERNIE","And hey — Tumble, your plates aren't scary. They're amazing.")],"warm"),
    ("s34","VALLEY",["REX","TUMBLE"],
     "Grandpa Rex warmly explaining, gesturing to Tumble's sunlit back plates which glow softly in the sun, a sparkle DINO FACT moment",
     "warm push-in, plates catch sunlight, sparkle", [("REX","Indeed. A Stegosaurus's back-plates soaked up the morning sun — to help him feel toasty and warm. Dino fact!")],"fact"),
    ("s35","VALLEY",["TUMBLE"],
     "Tumble absolutely delighted, beaming with pride about his plates",
     "joyful pop, confetti sparkle", [("TUMBLE","I'm a sun-warmer-upper?! That's the best thing anybody ever said about my plates!")],"fact"),
    # ---------- WRAP-UP + HUG ----------
    ("s36","VALLEY",["BERNIE","TUMBLE","PIP","SKY","ROSIE","REX"],
     "the whole group piles into a big gentle group cuddle, Tumble glowing in the middle, everyone happy",
     "warm group hug, slow embrace", [("TUMBLE","I'm not lonely anymore.")],"resolve"),
    ("s37","VALLEY",["BERNIE"],
     "Bernie turns warmly to camera with a heartfelt smile, friends behind him",
     "gentle push to camera address", [("BERNIE","Nope. You've got Valley Pals now. And you know what we learned? The bravest, kindest thing you can do… is just say hello.")],"resolve"),
    ("s38","VALLEY",["BERNIE","TUMBLE","PIP","SKY","ROSIE","REX"],
     "paws, wings, and tails all stack together in the middle in a team cheer, big smiles",
     "energetic team stack, push in", [("BERNIE","Valley Pals — here we go!")],"resolve"),
    # ---------- TAG / TEASER ----------
    ("s39","DOCK_DUSK",["BERNIE","PIP"],
     "back at the Pawford dock at dusk, Bernie tucked in half-asleep, Pip in his ear fluff, warm purple-orange sky",
     "cozy slow settle, dusk glow", [("BERNIE","Pip… if there's a Dino Valley… do you think there's a shy little Triceratops who needs a friend too?"),("PIP","Go to sleep, Bernie.")],"calm"),
    ("s40","DOCK_DUSK",["BERNIE","PIP"],
     "Bernie snoring softly with a dreamy smile, Pip peeks at the camera and smiles, lighthouse blinks in the background",
     "settle, lighthouse blink, fade", [("BERNIE","…Tomorrow. We'll say hello…"),("PIP","Tune in next time, everybody! Knowing him? We're TOTALLY making a new friend.")],"calm"),
]

def build_positive(location_key, chars, action):
    loc = LOCATIONS.get(location_key, "")
    block = char_block(chars)
    parts = [STYLE]
    if block: parts.append(block)
    if loc: parts.append(loc)
    parts.append(action)
    return ". ".join(parts)

def build_episode():
    shots = []
    for (sid, loc, chars, action, motion, dialogue, beat) in SHOTS:
        shots.append(dict(
            id=sid, location=loc, chars=chars,
            action=action,                                  # raw staging (Director-editable)
            positive=build_positive(loc, chars, action),
            negative=NEG,
            motion=motion,
            dialogue=[dict(speaker=s, line=l) for (s,l) in dialogue],
            beat=beat,
        ))
    ep = dict(title="Bernie Finds the Valley", episode=1, fps=24, shots=shots)
    return ep

if __name__ == "__main__":
    import pathlib
    ep = build_episode()
    out = pathlib.Path(__file__).resolve().parent.parent / "work" / "episode.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(ep, indent=2), encoding="utf-8")
    nd = sum(len(s["dialogue"]) for s in ep["shots"])
    print(f"episode.json written: {len(ep['shots'])} shots, {nd} dialogue lines -> {out}")
