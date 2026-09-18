VISION HELPER CONTRACT FOR DEEPSEEK LANES

The primary model is text-only. If and only if an image must be interpreted,
call the shared Gemini vision helper instead of sending image input to the
primary model:

    python3 /opt/vision_inspect.py IMAGE_PATH --purpose "bounded question"

Use the returned JSON as evidence. Keep each request narrowly scoped and do
not ask the helper to solve the task, browse the web, edit files, or make the
final decision. If no image interpretation is needed, do not call it.

