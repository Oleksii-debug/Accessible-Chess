# Accessible Chess third-party notices

This file records code that is copied or adapted into the Accessible Chess
repository. Candidate-only components that are not shipped are tracked
separately and are not licenses for this project.

## cbh2pgn

- Upstream: <https://github.com/asdfjkl/cbh2pgn>
- Pinned evidence source: `42b3592738062db1f768239e85df1b98cb1cead9`
- Use in Accessible Chess: adapted classic CBH, CBG, CBP, and CBT read-only
  record-layout primitives in `acs/chessbase_cbh.py`,
  `acs/chessbase_cbg.py`, `acs/chessbase_cbp.py`, and
  `acs/chessbase_cbt.py`, plus later modules that explicitly cite the same
  pinned source.
- Excluded: the upstream `python-chess` runtime dependency and any GPL code.
- Capability boundary: these adaptations do not currently decode classic CBG
  move or variation tokens and do not establish full ChessBase compatibility.

The following notice is reproduced from the pinned upstream `LICENSE` file:

> MIT License
>
> Copyright (c) 2022 Dominik Klein
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.
