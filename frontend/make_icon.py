from pathlib import Path

from PIL import Image, ImageDraw


def main() -> None:
    size = 256
    image = Image.new("RGBA", (size, size), "#080b12")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((10, 10, 246, 246), radius=54, fill="#101723", outline="#66e3dd", width=8)
    draw.polygon(((128, 40), (214, 128), (128, 216), (42, 128)), outline="#9b8cff", width=15)
    draw.polygon(((128, 73), (181, 128), (128, 183), (75, 128)), outline="#66e3dd", width=12)
    draw.ellipse((109, 109, 147, 147), fill="#edf4ff")
    output = Path(__file__).with_name("assets") / "delphiopt.ico"
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(output.resolve())


if __name__ == "__main__":
    main()
