#!/usr/bin/env python3
"""Previsualizar o imprimir un ticket descargado con la cola Epson explícita."""
import argparse
from pathlib import Path
import sys
import subprocess
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'local'))
from thermal_printing import inspect_pdf,queue_options,render,send


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('pdf');parser.add_argument('--printer',required=True)
    group=parser.add_mutually_exclusive_group();group.add_argument('--send',action='store_true');group.add_argument('--render-only',metavar='ARCHIVO_PRN')
    args=parser.parse_args()
    try:
        pdf=Path(args.pdf).resolve();height=inspect_pdf(pdf);queue_options(args.printer)
        if args.render_only:render(pdf,args.printer,Path(args.render_only).resolve(),height)
        elif args.send:print(send(pdf,args.printer,height))
        else:print(f'Cola: {args.printer}\nRollo: 80 mm · área útil: 72 mm\nRáster: 576 × {height} puntos · 203 dpi · una página\nCorte: por trabajo · reducción inferior\nSin envío. Usa --render-only para verificar o --send para imprimir una copia.')
    except (ValueError,OSError,subprocess.SubprocessError) as error:parser.exit(1,str(error)+'\n')

if __name__=='__main__':main()
