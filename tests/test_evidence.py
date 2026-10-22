from src.agent import apply_claims
from src.schemas import Offer


def test_fabricated_quote_cannot_fill_material_field():
    o=apply_claims(Offer(url='https://samsung.com/product'),{'condition':{'value':'new','quote':'Brand new retail unit'}},'Model X at $100')
    assert o.condition is None and not o.evidence


def test_conflicting_claim_not_silently_replaced():
    o=apply_claims(Offer(url='https://samsung.com/product',condition='refurbished'),{'condition':{'value':'new','quote':'New product'}},'New product')
    assert o.condition=='refurbished' and o.conflicts


def test_existing_product_name_cannot_prove_new_condition():
    o=apply_claims(Offer(url='https://samsung.com/product'),{'condition':{'value':'new','quote':'990 EVO Plus'}},'990 EVO Plus')
    assert o.condition is None


def test_ssd_bus_is_not_a_keyboard_switch():
    o=apply_claims(Offer(url='https://samsung.com/product',category='ssd'),{'switch':{'value':'PCIe 4.0','quote':'PCIe 4.0'}},'PCIe 4.0')
    assert o.switch is None


def test_seller_sku_quote_is_not_proof_of_manufacturer_part_number():
    text='{"sku": "Keychron_V1W-D3"}'
    o=apply_claims(Offer(url='https://keychron.com/product'),
                   {'mpn':{'value':'Keychron_V1W-D3','quote':text}},text)
    assert o.mpn is None


def test_switch_and_assembly_title_does_not_prove_keyboard_layout():
    text='Keyboard - Fully Assembled Knob / Black / Keychron Super Brown'
    o=apply_claims(Offer(url='https://keychron.com/product',category='keyboard'),
                   {'layout':{'value':'Keychron Super Brown','quote':text}},text)
    assert o.layout is None


def test_generic_socket_spec_does_not_override_selected_switch_title():
    text='Kailh hotswap sockets'
    o=apply_claims(Offer(url='https://keychron.com/product',category='keyboard',seller_sku='KC_A1',title='Keyboard - Red'),
                   {'switch':{'value':'Kailh hotswap sockets','quote':text}},text)
    assert o.switch is None


def test_order_control_and_boolean_do_not_establish_pack_count():
    for value,text in [(1,'Quantity: 1'),(True,'Pack quantity: 1')]:
        o=apply_claims(Offer(url='https://keychron.com/product'),
                       {'quantity':{'value':value,'quote':text}},text)
        assert o.quantity is None
