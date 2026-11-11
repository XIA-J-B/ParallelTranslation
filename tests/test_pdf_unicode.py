"""Read-only embedded-font Unicode recovery and conservative unknown handling."""
import copy
import hashlib
import io
import unittest

import pymupdf
from fontTools.fontBuilder import FontBuilder
from fontTools.misc.psCharStrings import T1CharString
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.t1Lib import T1Font

from pdf_unicode import _font_program, glyph_unicode, invalid_text, recover_page_text


def build_encoded_pdf(codes=b'\x10X\x11A\x01', *, rotation=0, size=(320, 440), columns=1, glyph_order=None):
    """A self-contained Type1 PDF with genuine control-code math glyphs.

    No paper sample or installed font is required. Glyph names are the semantic
    evidence; all glyphs deliberately use a simple test outline.
    """
    order=glyph_order or ['.notdef','parenleftBig','summationdisplay','parenrightBig','a','unknownGlyph']
    encoding=['.notdef']*256
    for code,name in [(16,'parenleftBig'),(88,'summationdisplay'),(17,'parenrightBig'),
                      (65,'a'),(1,'unknownGlyph'),(9,'parenleftBig'),(10,'parenrightBig')]:
        encoding[code]=name
    font=T1Font.__new__(T1Font)
    font.encoding='ascii'
    font.font={'FontName':'EncodingFixture','FontType':1,'PaintType':0,
        'FontMatrix':[.001,0,0,.001,0,0],'FontBBox':[0,0,500,700],'Encoding':encoding,
        'Private':{'RD':('string','currentfile','exch','readstring','pop'),
                   'ND':('noaccess','def'),'NP':('noaccess','put'),
                   'BlueValues':[],'MinFeature':[16,16],'password':5839,'lenIV':4,'Subrs':[]},
        'CharStrings':{name:T1CharString(program=[0,600,'hsbw',50,0,'rmoveto',0,700,'rlineto',
                     400,0,'rlineto',0,-700,'rlineto','closepath','endchar']) for name in order}}
    data=font.createData()
    with pymupdf.open() as pdf:
        page=pdf.new_page(width=size[0],height=size[1])
        program=pdf.get_new_xref()
        a=data.index(b'currentfile eexec ')+len(b'currentfile eexec ')
        b=data.index(b'\n'+b'0'*64,a)
        pdf.update_object(program,f'<< /Length1 {a} /Length2 {b-a} /Length3 {len(data)-b} >>')
        pdf.update_stream(program,data)
        descriptor=pdf.get_new_xref()
        pdf.update_object(descriptor,f'<< /Type /FontDescriptor /FontName /EncodingFixture /Flags 4 '
            f'/FontBBox [0 0 500 700] /ItalicAngle 0 /Ascent 700 /Descent 0 /CapHeight 700 /StemV 80 /FontFile {program} 0 R >>')
        font_id=pdf.get_new_xref()
        pdf.update_object(font_id,f'<< /Type /Font /Subtype /Type1 /BaseFont /EncodingFixture /FirstChar 0 /LastChar 255 '
            f'/Widths [{" ".join(["600"]*256)}] /FontDescriptor {descriptor} 0 R >>')
        resources=pdf.get_new_xref()
        pdf.update_object(resources,f'<< /Font << /Fixture {font_id} 0 R >> >>')
        pdf.xref_set_key(page.xref,'Resources',f'{resources} 0 R')
        contents=pdf.get_new_xref()
        commands=[]
        for column in range(columns):
            x=20+column*size[0]/columns
            commands.append(f'BT /Fixture 10 Tf 1 0 0 1 {x} {size[1]-50} Tm <{codes.hex()}> Tj ET')
        pdf.update_object(contents,'<<>>')
        pdf.update_stream(contents,'\n'.join(commands).encode('ascii'))
        page.set_contents(contents)
        page.set_rotation(rotation)
        return pdf.tobytes()


def build_cmap_pdf(*, mapped='\u03a9', glyph='unlabeledShape', corrupt=True):
    builder=FontBuilder(1000,isTTF=True)
    builder.setupGlyphOrder(['.notdef',glyph])
    builder.setupCharacterMap({ord(mapped):glyph})
    shapes={}
    for name in ['.notdef',glyph]:
        pen=TTGlyphPen(None)
        pen.moveTo((50,0));pen.lineTo((50,700));pen.lineTo((450,700));pen.lineTo((450,0));pen.closePath()
        shapes[name]=pen.glyph()
    builder.setupGlyf(shapes)
    builder.setupHorizontalMetrics({name:(600,0) for name in shapes})
    builder.setupHorizontalHeader(ascent=800,descent=-200)
    builder.setupNameTable({'familyName':'CmapFixture','styleName':'Regular','uniqueFontIdentifier':'CmapFixture',
                            'fullName':'CmapFixture','psName':'CmapFixture'})
    builder.setupOS2(sTypoAscender=800,sTypoDescender=-200,usWinAscent=800,usWinDescent=200)
    builder.setupPost()
    data=io.BytesIO();builder.save(data)
    with pymupdf.open() as pdf:
        page=pdf.new_page(width=320,height=440)
        font=page.insert_font(fontname='Fixture',fontbuffer=data.getvalue())
        page.insert_text((30,60),mapped,fontname='Fixture',fontsize=12)
        if corrupt:
            kind,reference=pdf.xref_get_key(font,'ToUnicode')
            assert kind=='xref'
            xref=int(reference.split()[0])
            stream=pdf.xref_stream(xref)
            encoded=f'<{ord(mapped):04x}>'.encode('ascii')
            # Replace only the Unicode target, keeping the glyph/source CID.
            assert encoded in stream
            stream=stream.replace(encoded,b'<fffd>')
            pdf.update_stream(xref,stream)
        return pdf.tobytes()


def build_cff_pdf():
    order=['.notdef','parenleftBig','summationdisplay','parenrightBig','a','unknownGlyph']
    builder=FontBuilder(1000,isTTF=False)
    builder.setupGlyphOrder(order)
    builder.setupCharacterMap({16:'parenleftBig',88:'summationdisplay',17:'parenrightBig',65:'a',1:'unknownGlyph'})
    builder.setupHorizontalMetrics({name:(600,0) for name in order})
    builder.setupHorizontalHeader(ascent=800,descent=-200)
    builder.setupNameTable({'familyName':'EncodingFixture','styleName':'Regular','uniqueFontIdentifier':'CffFixture',
                            'fullName':'EncodingFixture','psName':'EncodingFixture'})
    builder.setupOS2(sTypoAscender=800,sTypoDescender=-200,usWinAscent=800,usWinDescent=200)
    builder.setupPost()
    shapes={}
    for name in order:
        pen=T2CharStringPen(600,None)
        pen.moveTo((50,0));pen.lineTo((50,700));pen.lineTo((450,700));pen.lineTo((450,0));pen.closePath()
        shapes[name]=pen.getCharString()
    builder.setupCFF('EncodingFixture',{'FullName':'EncodingFixture','FamilyName':'EncodingFixture','Weight':'Regular'},shapes,{})
    buffer=io.BytesIO()
    builder.font['CFF '].cff.compile(buffer,builder.font)
    with pymupdf.open(stream=build_encoded_pdf(),filetype='pdf') as pdf:
        font_id=pdf[0].get_fonts()[0][0]
        descriptor=int(pdf.xref_get_key(font_id,'FontDescriptor')[1].split()[0])
        program=pdf.get_new_xref()
        pdf.update_object(program,'<< /Subtype /Type1C >>')
        pdf.update_stream(program,buffer.getvalue())
        pdf.xref_set_key(descriptor,'FontFile','null')
        pdf.xref_set_key(descriptor,'FontFile3',f'{program} 0 R')
        pdf.xref_set_key(font_id,'Encoding','<< /Type /Encoding /Differences [16 /parenleftBig 17 /parenrightBig 65 /a 88 /summationdisplay 1 /unknownGlyph] >>')
        return pdf.tobytes()


def characters(native):
    return [c for b in native['blocks'] for line in b.get('lines',[]) for s in line['spans'] for c in s['chars']]


class PdfUnicodeTests(unittest.TestCase):
    def test_type1_control_and_printable_codes_recover_at_actual_glyph_positions(self):
        for size,columns in [((320,440),1),((640,480),2),((420,600),1)]:
            for rotation in (0,90,180,270):
                with self.subTest(size=size,columns=columns,rotation=rotation),pymupdf.open(
                        stream=build_encoded_pdf(rotation=rotation,size=size,columns=columns),filetype='pdf') as pdf:
                    page=pdf[0]
                    native=page.get_text('rawdict')
                    baseline=copy.deepcopy(native)
                    before=hashlib.sha256(page.get_pixmap().samples).digest()
                    restored,diagnostics=recover_page_text(page,native)
                    self.assertEqual(native,baseline)
                    self.assertEqual(''.join(c['c'] for c in characters(restored)),'(\u2211)a\x01'*columns)
                    self.assertEqual(len(diagnostics['fixes']),3*columns)
                    self.assertEqual(len(diagnostics['unresolved']),columns)
                    self.assertEqual(before,hashlib.sha256(page.get_pixmap().samples).digest())
                    for old,new in zip(characters(native),characters(restored)):
                        self.assertEqual({k:v for k,v in old.items() if k!='c'}, {k:v for k,v in new.items() if k!='c'})

    def test_whitespace_control_codes_can_be_real_math_glyphs(self):
        with pymupdf.open(stream=build_encoded_pdf(b'\t\n'),filetype='pdf') as pdf:
            raw,diagnostics=recover_page_text(pdf[0])
            self.assertEqual(''.join(c['c'] for c in characters(raw)),'()')
            self.assertEqual(len(diagnostics['fixes']),2)

    def test_unicode_cmap_recovers_replacement_when_glyph_name_is_uninformative(self):
        with pymupdf.open(stream=build_cmap_pdf(),filetype='pdf') as pdf:
            self.assertTrue(any(invalid_text(c['c']) for c in characters(pdf[0].get_text('rawdict'))))
            raw,diagnostics=recover_page_text(pdf[0])
            self.assertEqual(''.join(c['c'] for c in characters(raw)),'\u03a9')
            self.assertEqual(diagnostics['fixes'][0]['method'],'embedded-unicode-cmap')

    def test_embedded_cff_uses_its_real_glyph_order(self):
        with pymupdf.open(stream=build_cff_pdf(),filetype='pdf') as pdf:
            self.assertEqual(pdf[0].get_fonts()[0][1],'cff')
            raw,diagnostics=recover_page_text(pdf[0])
            self.assertEqual(''.join(c['c'] for c in characters(raw)),'(\u2211)a\x01')
            self.assertEqual(len(diagnostics['fixes']),3)
            self.assertEqual(len(diagnostics['unresolved']),1)

    def test_valid_explicit_unicode_remains_authoritative_for_ordinary_text(self):
        with pymupdf.open(stream=build_cmap_pdf(mapped='A',glyph='B',corrupt=False),filetype='pdf') as pdf:
            raw,diagnostics=recover_page_text(pdf[0])
            self.assertEqual(''.join(c['c'] for c in characters(raw)),'A')
            self.assertFalse(diagnostics['fixes'])

    def test_unknown_private_use_glyph_is_reported_instead_of_claiming_reliable_text(self):
        with pymupdf.open(stream=build_encoded_pdf(b'\x01'),filetype='pdf') as pdf:
            font=pdf[0].get_fonts()[0][0]
            cmap=pdf.get_new_xref()
            pdf.update_object(cmap,'<<>>')
            pdf.update_stream(cmap,b'/CIDInit /ProcSet findresource begin 12 dict begin begincmap '
                b'/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def '
                b'/CMapName /PrivateMap def /CMapType 2 def 1 begincodespacerange <00> <ff> endcodespacerange '
                b'1 beginbfchar <01> <f8ff> endbfchar endcmap CMapName currentdict /CMap defineresource pop end end')
            pdf.xref_set_key(font,'ToUnicode',f'{cmap} 0 R')
            self.assertIn('\uf8ff',pdf[0].get_text())
            _,diagnostics=recover_page_text(pdf[0])
            self.assertEqual(len(diagnostics['unresolved']),1)
            self.assertEqual(diagnostics['unresolved'][0]['before'],'\uf8ff')

    def test_type1_notdef_order_matches_renderer_glyph_ids(self):
        order=['parenleftBig','.notdef','summationdisplay','parenrightBig','a','unknownGlyph']
        with pymupdf.open(stream=build_encoded_pdf(b'\x10X\x11',glyph_order=order),filetype='pdf') as pdf:
            restored,diag=recover_page_text(pdf[0])
            self.assertEqual(''.join(c['c'] for c in characters(restored)),'(\u2211)')
            self.assertFalse(diag['unresolved'])

    def test_same_named_distinct_font_resources_require_consensus(self):
        swapped=['.notdef','parenrightBig','summationdisplay','parenleftBig','a','unknownGlyph']
        with pymupdf.open(stream=build_encoded_pdf(b'\x10'),filetype='pdf') as pdf, pymupdf.open(
                stream=build_encoded_pdf(b'\x10',glyph_order=swapped),filetype='pdf') as other:
            pdf.insert_pdf(other)
            first_font=pdf[0].get_fonts()[0][0]
            second_font=pdf[1].get_fonts()[0][0]
            resource=int(pdf.xref_get_key(pdf[0].xref,'Resources')[1].split()[0])
            pdf.xref_set_key(resource,'Font',f'<< /Fixture {first_font} 0 R /Other {second_font} 0 R >>')
            _,diag=recover_page_text(pdf[0])
            self.assertFalse(diag['fixes'])
            self.assertEqual(len(diag['unresolved']),1)

    def test_standard_math_variants_and_components_do_not_use_private_characters(self):
        for name,expected in [('parenleftBig','('),('summationdisplay','\u2211'),('radicalBig','\u221a'),
                              ('parenlefttp','\u239b'),('bracerightbt','\u23ad')]:
            self.assertEqual(glyph_unicode(name)[0],expected)
        self.assertIsNone(glyph_unicode('unknownGlyph')[0])
        self.assertIsNone(glyph_unicode('atext')[0])
        self.assertEqual(glyph_unicode('f_f_i')[0],'ffi')

    def test_invalid_and_ambiguous_font_programs_fail_closed(self):
        self.assertIsNone(_font_program(b'not a font','pfa'))
        self.assertTrue(invalid_text('\x00'))
        self.assertTrue(invalid_text('\x85'))
        self.assertFalse(invalid_text('A\u2211'))


if __name__=='__main__':
    unittest.main()
