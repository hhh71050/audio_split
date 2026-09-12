import asyncio
import edge_tts
from pydub import AudioSegment

async def text_to_standard_wav(text, output_path):
    # 使用标准中文播音音色，语速适当放缓 5%
    communicate = edge_tts.Communicate(text, "zh-CN-YunxiNeural", rate="-5%")
    raw_mp3 = "temp.mp3"
    await communicate.save(raw_mp3)
    
    # 后处理：转为 ASR 标准的 16kHz 单声道 PCM WAV，并增加首尾静音 padding
    audio = AudioSegment.from_file(raw_mp3)
    audio = audio.set_frame_rate(16000).set_channels(1)
    
    padding = AudioSegment.silent(duration=150)  # 150ms 静音
    final_audio = padding + audio + padding
    final_audio.export(output_path, format="wav")

# 使用示例
asyncio.run(text_to_standard_wav(
    "这是一个用于测试 ASR 识别率的标准文本片段。",
    "test_standard.wav"
))