# StatGarten maps — 전국·부산 행정경계 출처 및 라이선스

전략 대시보드의 전국 시도 경계와 부산 구·군 경계 geometry는 `statgarten/maps` 저장소의 SGIS-derived SVG를 기반으로 한다.

## 전국 시도 경계

- upstream repository: `https://github.com/statgarten/maps`
- source file: `svg/simple/전국_시도_경계.svg`
- pinned upstream commit: `d5f8ea3208f19a73a01f865847d20cc195ae91ba`
- source blob: `2a97985e7b0e0d3e0653ab37f55677a768b864f0`
- geometry 기준연도: **2020**
- upstream 설명: 통계청 SGIS Open API에서 수집한 행정구역 경계를 SVG로 가공
- repository copy: `web/assets/korea-sido.svg`

저장소 사본은 원본 17개 시도 path에서 임의로 경계를 다시 그리지 않는다. 화면용 파일 크기를 줄이기 위해 원본 800×759 좌표계에 **Douglas-Peucker tolerance 2.5 SVG units**(약 0.3%)를 적용했고, `preserve_topology=True`로 위상을 보존했다. 시도 ID, 다중 도서 subpath, 제주 분리 구조를 유지하며 다크톤 dashboard 표현용 fill/stroke와 접근성 title/description을 추가했다.

이 단순화는 **표현 layer 전용**이다. 금리 데이터, 지역 분류, 집계, canonical identity에는 사용하지 않는다. 더 높은 해상도가 필요해지면 같은 pinned source에서 tolerance를 낮춰 다시 생성한다.

## 부산 구·군 경계

- upstream repository: `https://github.com/statgarten/maps`
- source file: `svg/simple/부산광역시_시군구_경계.svg`
- pinned upstream commit: `d5f8ea3208f19a73a01f865847d20cc195ae91ba`
- source blob: `b37b1ea14354f5d8794d3ac7406f00dda2de3d58`
- geometry 기준연도: **2020**
- upstream 설명: 통계청 SGIS Open API에서 수집한 행정구역 경계를 SVG로 가공

이 geometry들을 최신 행정경계라고 표현하지 않는다. 전략 화면에는 기준연도와 출처를 함께 표시한다. 향후 SGIS의 더 최신 geometry로 갱신할 때에는 당시 공식 API의 기준연도, 인증 방식, 이용조건을 다시 검증한다.

금리 데이터와 경계 데이터는 서로 다른 계약이다. 지도에 시도 또는 구·군 경계가 존재한다는 이유만으로 금리를 생성하거나 다른 지역의 금리를 복제하지 않는다. 특히 부산은 canonical `district` 데이터가 없는 구·군을 계속 `데이터 없음`으로 취급한다.

## Upstream license

MIT License

Copyright (c) 2022 StatGarten

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
