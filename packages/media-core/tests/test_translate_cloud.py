from media_core.translate import CloudTranslator


class FakeResponse:
    def __init__(self, content: str):
        self.choices = [type("Choice", (), {"message": type("Msg", (), {"content": content})()})()]


class FakeChatClient:
    def __init__(self, content: str = "translated"):
        self.calls = []
        self.chat = self
        self.completions = self
        self._content = content

    def create(self, model, messages, temperature=0.0):  # pragma: no cover - trivial
        self.calls.append({"model": model, "messages": messages, "temperature": temperature})
        return FakeResponse(self._content)


class FailingChatClient(FakeChatClient):
    def create(self, *args, **kwargs):  # pragma: no cover - trivial
        raise RuntimeError("boom")


def test_cloud_translator_uses_chat_client_and_returns_content():
    client = FakeChatClient(content="hola")
    translator = CloudTranslator(client=client, model="demo", system_prompt="translate {src} to {tgt}", temperature=0.2)

    out = translator.translate_batch(["hello"], src="en", tgt="es")

    assert out == ["hola"]
    assert client.calls[0]["model"] == "demo"
    assert "en" in client.calls[0]["messages"][0]["content"]
    assert "es" in client.calls[0]["messages"][0]["content"]


def test_cloud_translator_falls_back_to_original_on_error():
    client = FailingChatClient()
    translator = CloudTranslator(client=client, model="demo")

    out = translator.translate_batch(["keep me"], src="en", tgt="fr")

    assert out == ["keep me"]
