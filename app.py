from flask import Flask, request, jsonify, send_file, render_template, Response
import yt_dlp
import os
import tempfile
import json
import re

app = Flask(__name__)

# ---------- Yardımcı Fonksiyonlar ----------

def format_duration(seconds):
    if not seconds:
        return "Bilinmiyor"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

def format_views(count):
    if not count:
        return "0"
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.1f}K"
    return str(count)

# ---------- Rotalar ----------

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/info', methods=['POST'])
def get_info():
    data = request.get_json()
    url = (data or {}).get('url', '').strip()

    if not url:
        return jsonify({'error': 'URL gerekli'}), 400

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        # Kalite seçeneklerini derle
        seen = set()
        qualities = []
        for f in info.get('formats', []):
            h = f.get('height')
            vcodec = f.get('vcodec', 'none')
            if h and vcodec != 'none' and h not in seen:
                seen.add(h)
                qualities.append({'label': f'{h}p', 'value': str(h)})

        qualities = sorted(qualities, key=lambda x: int(x['value']), reverse=True)[:6]
        if not qualities:
            qualities = [{'label': 'En İyi', 'value': 'best'}]

        return jsonify({
            'title': info.get('title', 'Başlıksız'),
            'thumbnail': info.get('thumbnail', ''),
            'duration': format_duration(info.get('duration')),
            'uploader': info.get('uploader', 'Bilinmiyor'),
            'view_count': format_views(info.get('view_count')),
            'qualities': qualities,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/download')
def download():
    url = request.args.get('url', '').strip()
    fmt = request.args.get('format', 'mp4')  # 'mp4' veya 'mp3'
    quality = request.args.get('quality', 'best')

    if not url:
        return jsonify({'error': 'URL gerekli'}), 400

    tmp_dir = tempfile.mkdtemp()
    output_template = os.path.join(tmp_dir, '%(title).80s.%(ext)s')

    try:
        if fmt == 'mp3':
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': output_template,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'quiet': True,
                'no_warnings': True,
            }
        else:
            if quality == 'best':
                fmt_str = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best'
            else:
                fmt_str = (
                    f'bestvideo[height<={quality}][ext=mp4]+bestaudio[ext=m4a]/'
                    f'bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best'
                )
            ydl_opts = {
                'format': fmt_str,
                'outtmpl': output_template,
                'merge_output_format': 'mp4',
                'quiet': True,
                'no_warnings': True,
            }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # İndirilen dosyayı bul
        files = [f for f in os.listdir(tmp_dir) if os.path.isfile(os.path.join(tmp_dir, f))]
        if not files:
            return jsonify({'error': 'Dosya oluşturulamadı'}), 500

        file_path = os.path.join(tmp_dir, files[0])
        mime = 'audio/mpeg' if fmt == 'mp3' else 'video/mp4'

        def generate():
            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(1024 * 1024)  # 1MB chunk
                    if not chunk:
                        break
                    yield chunk
            # Dosyayı ve klasörü temizle
            try:
                os.remove(file_path)
                os.rmdir(tmp_dir)
            except Exception:
                pass

        response = Response(
            generate(),
            mimetype=mime,
            headers={
                'Content-Disposition': f'attachment; filename="{os.path.basename(file_path)}"',
                'X-Content-Type-Options': 'nosniff',
            }
        )
        return response

    except Exception as e:
        # Temizlik
        try:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
