from clap_launcher import ClapDetector


def test_two_claps_within_window_trigger():
    d = ClapDetector(threshold=0.2, refractory=0.15, window=0.8)
    assert d.process(0.05, 0.0) is False  # silencio
    assert d.process(0.5, 1.0) is False  # primer aplauso
    assert d.process(0.05, 1.05) is False  # silencio entre aplausos
    assert d.process(0.5, 1.3) is True  # segundo aplauso, dentro de la ventana


def test_single_clap_never_triggers():
    d = ClapDetector(threshold=0.2, refractory=0.15, window=0.8)
    assert d.process(0.5, 1.0) is False
    assert d.process(0.05, 1.2) is False
    assert d.process(0.05, 5.0) is False


def test_claps_too_far_apart_reset_instead_of_triggering():
    d = ClapDetector(threshold=0.2, refractory=0.15, window=0.8)
    assert d.process(0.5, 1.0) is False  # aplauso "huérfano"
    assert d.process(0.05, 1.2) is False
    # pasa mucho más que la ventana permitida antes del siguiente
    assert d.process(0.5, 5.0) is False  # se toma como un NUEVO primer aplauso
    assert d.process(0.05, 5.2) is False
    assert d.process(0.5, 5.4) is True  # este sí completa el doble, contra el de 5.0


def test_sustained_loud_sound_is_not_two_claps():
    d = ClapDetector(threshold=0.2, refractory=0.15, window=0.8)
    assert d.process(0.5, 1.0) is False
    # sigue fuerte sin bajar de umbral -> nunca vuelve a "quiet_since_last"
    assert d.process(0.5, 1.05) is False
    assert d.process(0.5, 1.10) is False
    assert d.process(0.5, 1.20) is False


def test_ambient_noise_below_threshold_never_triggers():
    d = ClapDetector(threshold=0.2, refractory=0.15, window=0.8)
    for i in range(50):
        assert d.process(0.01, i * 0.02) is False
