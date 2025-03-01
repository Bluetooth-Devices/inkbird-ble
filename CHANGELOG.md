# CHANGELOG


## v0.7.1 (2025-03-01)

### Bug Fixes

- Add missing humid sensor on newer TH2 models that have it
  ([#64](https://github.com/Bluetooth-Devices/inkbird-ble/pull/64),
  [`e6283ad`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/e6283ada62bfe3794c37889b1a82f5e72eef1d18))

### Chores

- **ci**: Bump the github-actions group with 2 updates
  ([#63](https://github.com/Bluetooth-Devices/inkbird-ble/pull/63),
  [`0929e03`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/0929e031bc3088570cc0698dd3e2a9ad492301a2))

Bumps the github-actions group with 2 updates:
  [python-semantic-release/python-semantic-release](https://github.com/python-semantic-release/python-semantic-release)
  and
  [python-semantic-release/publish-action](https://github.com/python-semantic-release/publish-action).

Updates `python-semantic-release/python-semantic-release` from 9.20.0 to 9.21.0 - [Release
  notes](https://github.com/python-semantic-release/python-semantic-release/releases) -
  [Changelog](https://github.com/python-semantic-release/python-semantic-release/blob/master/CHANGELOG.rst)
  -
  [Commits](https://github.com/python-semantic-release/python-semantic-release/compare/v9.20.0...v9.21.0)

Updates `python-semantic-release/publish-action` from 9.20.0 to 9.21.0 - [Release
  notes](https://github.com/python-semantic-release/publish-action/releases) -
  [Changelog](https://github.com/python-semantic-release/publish-action/blob/main/releaserc.toml) -
  [Commits](https://github.com/python-semantic-release/publish-action/compare/v9.20.0...v9.21.0)

--- updated-dependencies: - dependency-name: python-semantic-release/python-semantic-release
  dependency-type: direct:production

update-type: version-update:semver-minor

dependency-group: github-actions

- dependency-name: python-semantic-release/publish-action dependency-type: direct:production

dependency-group: github-actions ...

Signed-off-by: dependabot[bot] <support@github.com>

Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>

- **deps**: Bump myst-parser from 1.0.0 to 3.0.1
  ([#61](https://github.com/Bluetooth-Devices/inkbird-ble/pull/61),
  [`7708961`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/77089618c5503e6041deca0e467506e5c100bd32))

Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>

- **deps**: Bump sphinx-rtd-theme from 2.0.0 to 3.0.2
  ([#62](https://github.com/Bluetooth-Devices/inkbird-ble/pull/62),
  [`564fb88`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/564fb882bdab262af23d2d1344d445caf2a007d8))

Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>

- **pre-commit.ci**: Pre-commit autoupdate
  ([#60](https://github.com/Bluetooth-Devices/inkbird-ble/pull/60),
  [`65febcf`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/65febcfd2cd9835d339ec2526c44b5114bc7f80d))

Co-authored-by: pre-commit-ci[bot] <66853113+pre-commit-ci[bot]@users.noreply.github.com>


## v0.7.0 (2025-02-20)

### Chores

- Switch to ruff ([#58](https://github.com/Bluetooth-Devices/inkbird-ble/pull/58),
  [`d483e9d`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/d483e9d7a194129a84f6751fa456fbe31d858dee))

- Update dependabot.yml
  ([`63b15b6`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/63b15b6271e55cfa12f0709790fb18e2084f3b9f))

- **ci**: Bump the github-actions group with 6 updates
  ([#56](https://github.com/Bluetooth-Devices/inkbird-ble/pull/56),
  [`ffb5b0c`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/ffb5b0ce29f7035138aaca8779bf7e09cc6c01c5))

Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>

Co-authored-by: J. Nick Koston <nick@koston.org>

- **deps**: Bump sphinx from 5.3.0 to 6.2.1
  ([#57](https://github.com/Bluetooth-Devices/inkbird-ble/pull/57),
  [`897212c`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/897212c1f3484bf54eb8ab434e67cef8002fdd52))

Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>

### Features

- Switch to GH trusted publishing for PyPI
  ([#59](https://github.com/Bluetooth-Devices/inkbird-ble/pull/59),
  [`a017e3a`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/a017e3af6d31a16a9cccdde98e27855e9e219ca0))


## v0.6.0 (2025-02-20)

### Chores

- Add poetry cache to CI ([#54](https://github.com/Bluetooth-Devices/inkbird-ble/pull/54),
  [`47101db`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/47101db85fb7815072014f88abcfb9b85debffcd))

- Add some adv data from an ith-21-b
  ([#43](https://github.com/Bluetooth-Devices/inkbird-ble/pull/43),
  [`b86af8a`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/b86af8a813175d7437b788da0600f7bc822e1730))

- Create dependabot.yml
  ([`d719e63`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/d719e63d29e064b713adf55b3f87d4b8bda06a50))

- Fix codecov ([#55](https://github.com/Bluetooth-Devices/inkbird-ble/pull/55),
  [`6ef0734`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/6ef07340e93605d94d35310ff496b66007c59f84))

- Update Python versions ([#52](https://github.com/Bluetooth-Devices/inkbird-ble/pull/52),
  [`0eed983`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/0eed98378ac0bf5cf0068124d6e1bcbc5bc3f22b))

- **deps**: Bump myst-parser from 0.18.1 to 1.0.0
  ([#49](https://github.com/Bluetooth-Devices/inkbird-ble/pull/49),
  [`613b2ce`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/613b2cedc8cbf3292a3575428320caefd61c75a0))

Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>

- **deps**: Bump sphinx-rtd-theme from 1.3.0 to 2.0.0
  ([#48](https://github.com/Bluetooth-Devices/inkbird-ble/pull/48),
  [`e1a94a1`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/e1a94a1ad46750b69cf246dd160dae18dff4f2fd))

Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>

- **deps-dev**: Bump pytest from 7.4.4 to 8.3.4
  ([#53](https://github.com/Bluetooth-Devices/inkbird-ble/pull/53),
  [`263753d`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/263753d365a3e6262f259041771e71b0d2b86a27))

Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>

- **deps-dev**: Bump pytest-cov from 3.0.0 to 6.0.0
  ([#51](https://github.com/Bluetooth-Devices/inkbird-ble/pull/51),
  [`aed72d9`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/aed72d9bd8c31251984ab8420b7145743f0e8261))

Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>

- **pre-commit.ci**: Pre-commit autoupdate
  ([#28](https://github.com/Bluetooth-Devices/inkbird-ble/pull/28),
  [`9c565a4`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/9c565a4be62d6a54d79bc7af43a2e5f62ed96cdd))

Co-authored-by: pre-commit-ci[bot] <66853113+pre-commit-ci[bot]@users.noreply.github.com>

- **pre-commit.ci**: Pre-commit autoupdate
  ([#29](https://github.com/Bluetooth-Devices/inkbird-ble/pull/29),
  [`5a3360f`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/5a3360fbcb6c5f99968b8c3ba9fdd85c254c3b2c))

Co-authored-by: pre-commit-ci[bot] <66853113+pre-commit-ci[bot]@users.noreply.github.com>

- **pre-commit.ci**: Pre-commit autoupdate
  ([#30](https://github.com/Bluetooth-Devices/inkbird-ble/pull/30),
  [`e2996c0`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/e2996c0abde2e3b3722da10882f69d065304cc65))

Co-authored-by: pre-commit-ci[bot] <66853113+pre-commit-ci[bot]@users.noreply.github.com>

- **pre-commit.ci**: Pre-commit autoupdate
  ([#31](https://github.com/Bluetooth-Devices/inkbird-ble/pull/31),
  [`a0907bc`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/a0907bceb8120c4a0293c3ffa6bff9939b4bbc86))

Co-authored-by: pre-commit-ci[bot] <66853113+pre-commit-ci[bot]@users.noreply.github.com>

- **pre-commit.ci**: Pre-commit autoupdate
  ([#32](https://github.com/Bluetooth-Devices/inkbird-ble/pull/32),
  [`e64a9e0`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/e64a9e0dc08927d930f773e121b2d87ff1fcbead))

Co-authored-by: pre-commit-ci[bot] <66853113+pre-commit-ci[bot]@users.noreply.github.com>

- **pre-commit.ci**: Pre-commit autoupdate
  ([#33](https://github.com/Bluetooth-Devices/inkbird-ble/pull/33),
  [`f175c26`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/f175c26955f7d35e50a9b20603a92cfbc6f4c880))

Co-authored-by: pre-commit-ci[bot] <66853113+pre-commit-ci[bot]@users.noreply.github.com>

- **pre-commit.ci**: Pre-commit autoupdate
  ([#36](https://github.com/Bluetooth-Devices/inkbird-ble/pull/36),
  [`85f9934`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/85f9934619e9faea543b58031ca78b41e4306e98))

Co-authored-by: pre-commit-ci[bot] <66853113+pre-commit-ci[bot]@users.noreply.github.com>

- **pre-commit.ci**: Pre-commit autoupdate
  ([#38](https://github.com/Bluetooth-Devices/inkbird-ble/pull/38),
  [`7a413de`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/7a413de6f574f01f6904ea69e0e54da12a11f64c))

Co-authored-by: pre-commit-ci[bot] <66853113+pre-commit-ci[bot]@users.noreply.github.com>

- **pre-commit.ci**: Pre-commit autoupdate
  ([#39](https://github.com/Bluetooth-Devices/inkbird-ble/pull/39),
  [`cb5ceea`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/cb5ceeac9d7a2dd6d923c8ca5b7ddd220ef798a3))

Co-authored-by: pre-commit-ci[bot] <66853113+pre-commit-ci[bot]@users.noreply.github.com>

- **pre-commit.ci**: Pre-commit autoupdate
  ([#40](https://github.com/Bluetooth-Devices/inkbird-ble/pull/40),
  [`d6244d6`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/d6244d68172e607e2783db3b511211bc441d3ae1))

- **pre-commit.ci**: Pre-commit autoupdate
  ([#42](https://github.com/Bluetooth-Devices/inkbird-ble/pull/42),
  [`cf478cc`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/cf478ccd0a97362e5a74b4e16a24342c89a5951f))

Co-authored-by: pre-commit-ci[bot] <66853113+pre-commit-ci[bot]@users.noreply.github.com>

- **pre-commit.ci**: Pre-commit autoupdate
  ([#44](https://github.com/Bluetooth-Devices/inkbird-ble/pull/44),
  [`fbb7572`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/fbb7572828d6f6881fa8194d821b99a43ce412b7))

Co-authored-by: pre-commit-ci[bot] <66853113+pre-commit-ci[bot]@users.noreply.github.com>

- **pre-commit.ci**: Pre-commit autoupdate
  ([#46](https://github.com/Bluetooth-Devices/inkbird-ble/pull/46),
  [`7ac44d2`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/7ac44d239b2b912c2c93406b033af9a627f39c2c))

Co-authored-by: pre-commit-ci[bot] <66853113+pre-commit-ci[bot]@users.noreply.github.com>

### Features

- Add support for passing in the model
  ([#47](https://github.com/Bluetooth-Devices/inkbird-ble/pull/47),
  [`886b180`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/886b1805eb38f4800785b31e3a55460d9bd7b045))


## v0.5.8 (2024-07-03)

### Bug Fixes

- Handle sps broadcasting N0BYD ([#27](https://github.com/Bluetooth-Devices/inkbird-ble/pull/27),
  [`4686f57`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/4686f57b1864fbe7163e3f82bb6f788a137baf6a))


## v0.5.7 (2024-07-03)

### Bug Fixes

- Switch data change detection algorithm to use newer method
  ([#25](https://github.com/Bluetooth-Devices/inkbird-ble/pull/25),
  [`b41b1d6`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/b41b1d64c34c9b46ea6085c1911d2b2fc9336768))

### Chores

- Fix ci ([#26](https://github.com/Bluetooth-Devices/inkbird-ble/pull/26),
  [`eadb3fd`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/eadb3fdb2be292c74fd2a82a9cf019414ff452a3))

- **pre-commit.ci**: Pre-commit autoupdate
  ([#24](https://github.com/Bluetooth-Devices/inkbird-ble/pull/24),
  [`0eddeb7`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/0eddeb7f3fb184a555b1d3f1a2f40d7f72731725))

* chore(pre-commit.ci): pre-commit autoupdate

updates: - [github.com/commitizen-tools/commitizen: v2.28.0 →
  v3.27.0](https://github.com/commitizen-tools/commitizen/compare/v2.28.0...v3.27.0) -
  [github.com/pre-commit/pre-commit-hooks: v4.3.0 →
  v4.6.0](https://github.com/pre-commit/pre-commit-hooks/compare/v4.3.0...v4.6.0) -
  [github.com/pre-commit/mirrors-prettier: v2.7.1 →
  v4.0.0-alpha.8](https://github.com/pre-commit/mirrors-prettier/compare/v2.7.1...v4.0.0-alpha.8) -
  [github.com/asottile/pyupgrade: v2.37.1 →
  v3.16.0](https://github.com/asottile/pyupgrade/compare/v2.37.1...v3.16.0) -
  [github.com/PyCQA/isort: 5.12.0 → 5.13.2](https://github.com/PyCQA/isort/compare/5.12.0...5.13.2)
  - [github.com/psf/black: 22.6.0 → 24.4.2](https://github.com/psf/black/compare/22.6.0...24.4.2) -
  [github.com/codespell-project/codespell: v2.1.0 →
  v2.3.0](https://github.com/codespell-project/codespell/compare/v2.1.0...v2.3.0) -
  [github.com/PyCQA/flake8: 4.0.1 → 7.1.0](https://github.com/PyCQA/flake8/compare/4.0.1...7.1.0) -
  [github.com/pre-commit/mirrors-mypy: v0.931 →
  v1.10.1](https://github.com/pre-commit/mirrors-mypy/compare/v0.931...v1.10.1) -
  [github.com/PyCQA/bandit: 1.7.4 → 1.7.9](https://github.com/PyCQA/bandit/compare/1.7.4...1.7.9)

* chore(pre-commit.ci): auto fixes

---------

Co-authored-by: pre-commit-ci[bot] <66853113+pre-commit-ci[bot]@users.noreply.github.com>


## v0.5.6 (2023-02-06)

### Bug Fixes

- Account for switching adapter when finding changed_manufacturer_data
  ([#20](https://github.com/Bluetooth-Devices/inkbird-ble/pull/20),
  [`37400d0`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/37400d0a65fe3ff347ffb554fd0da4f8b78a187f))

- Bump python-semantic-release ([#21](https://github.com/Bluetooth-Devices/inkbird-ble/pull/21),
  [`64d17d7`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/64d17d7d90a49f882143cc3fb079cfa6ef488bcb))

- Update isort to fix CI ([#19](https://github.com/Bluetooth-Devices/inkbird-ble/pull/19),
  [`174b482`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/174b4825397add3b5f878d63e44aa108b3556b7e))


## v0.5.5 (2022-08-14)

### Bug Fixes

- Use new changed_manufacturer_data helper to remove bad data
  ([#18](https://github.com/Bluetooth-Devices/inkbird-ble/pull/18),
  [`cc4fcb2`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/cc4fcb2f14f3ba468bc634621883a2cb688f9feb))


## v0.5.4 (2022-08-14)

### Bug Fixes

- Parser when there are multiple manufacturer_data fields present
  ([#17](https://github.com/Bluetooth-Devices/inkbird-ble/pull/17),
  [`a4a9047`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/a4a9047816f22f2703b1109d62cf5c22e2ee09cb))


## v0.5.3 (2022-08-14)

### Bug Fixes

- Xbbq2 bad data ([#16](https://github.com/Bluetooth-Devices/inkbird-ble/pull/16),
  [`76b44d5`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/76b44d5bffd36750e8316a70dc27e4148c415687))


## v0.5.2 (2022-08-08)

### Bug Fixes

- Some IBBQ2 identify with xBBQ ([#15](https://github.com/Bluetooth-Devices/inkbird-ble/pull/15),
  [`0ebc14c`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/0ebc14c962ab95f6e76a69194f8bcd0d784345a0))

### Chores

- Add more tests ([#14](https://github.com/Bluetooth-Devices/inkbird-ble/pull/14),
  [`7e8369f`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/7e8369f728de6d745925913ce2348469605377a3))


## v0.5.1 (2022-07-21)

### Bug Fixes

- Bump sensor-state-data to fix typing
  ([#13](https://github.com/Bluetooth-Devices/inkbird-ble/pull/13),
  [`e7b1610`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/e7b161063899d34ae665e39ea425beb1db468f84))


## v0.5.0 (2022-07-21)

### Features

- Refactor for sensor-state-data 2 ([#12](https://github.com/Bluetooth-Devices/inkbird-ble/pull/12),
  [`02d7ca1`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/02d7ca1435e3aa98b7c46f7cf6bbbf9285330973))


## v0.4.0 (2022-07-20)

### Features

- Export SensorDescription and SensorValue
  ([#11](https://github.com/Bluetooth-Devices/inkbird-ble/pull/11),
  [`d362302`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/d362302b9f707abde4a4280422788010c01ff437))


## v0.3.2 (2022-07-20)

### Bug Fixes

- Bump deps ([#9](https://github.com/Bluetooth-Devices/inkbird-ble/pull/9),
  [`714cb68`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/714cb686f25ee4cd647ec1aafff774a8b47522f3))

- Test names ([#10](https://github.com/Bluetooth-Devices/inkbird-ble/pull/10),
  [`1379ea8`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/1379ea837ad5d80f885170d1545a64a057d2663c))


## v0.3.1 (2022-07-20)

### Bug Fixes

- Ibbq parser ([#8](https://github.com/Bluetooth-Devices/inkbird-ble/pull/8),
  [`1844d9f`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/1844d9fa659349685265e77ba079a87d68c4c6a0))


## v0.3.0 (2022-07-19)

### Features

- Set manufacturer ([#7](https://github.com/Bluetooth-Devices/inkbird-ble/pull/7),
  [`d0ba693`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/d0ba693652a083f208423aca6fd7a2e6742cff2a))


## v0.2.4 (2022-07-19)

### Bug Fixes

- Add guards to avoid matching unexpected devices
  ([#6](https://github.com/Bluetooth-Devices/inkbird-ble/pull/6),
  [`3a47dd7`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/3a47dd7ba3b9da547b5f7c1f32fcafae0bb9cee9))


## v0.2.3 (2022-07-19)

### Bug Fixes

- Parsing bbq data ([#5](https://github.com/Bluetooth-Devices/inkbird-ble/pull/5),
  [`7b2fe02`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/7b2fe02005021c2f5c15372f795c4777fbbb3d9c))


## v0.2.2 (2022-07-19)

### Bug Fixes

- Fix processing empty mfr data ([#4](https://github.com/Bluetooth-Devices/inkbird-ble/pull/4),
  [`1730e18`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/1730e18e75c7f345cce39db0f5234717602c2ae8))


## v0.2.1 (2022-07-19)

### Bug Fixes

- Bump libs ([#3](https://github.com/Bluetooth-Devices/inkbird-ble/pull/3),
  [`7d6d00b`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/7d6d00ba3b02404cf128df26b2093a1ff9a3f36b))


## v0.2.0 (2022-07-19)

### Features

- First publish ([#2](https://github.com/Bluetooth-Devices/inkbird-ble/pull/2),
  [`9b0b9ba`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/9b0b9ba5114c94a046a78a018f67423cc57df61a))


## v0.1.0 (2022-07-19)

### Chores

- Initial commit
  ([`176cb19`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/176cb19ab5431902e705feb48d31fa660019f027))

### Features

- Init repo ([#1](https://github.com/Bluetooth-Devices/inkbird-ble/pull/1),
  [`2920480`](https://github.com/Bluetooth-Devices/inkbird-ble/commit/29204806c2a5a9ab1b53ea268fbb4e7e5123b624))
