#
#  Copyright 2024 The InfiniFlow Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#

# Modified: package-local, immutable dictionary; no Redis or runtime WordNet download.
import json
import re
from pathlib import Path


class Dealer:
    def __init__(self):
        with (Path(__file__).parent / 'res' / 'synonym.json').open(encoding='utf-8') as stream:
            self.dictionary = {k.lower(): v for k, v in json.load(stream).items()}

    def lookup(self, tk, topn=8):
        if not isinstance(tk, str) or not tk:
            return []
        key = re.sub(r"[ \t]+", " ", tk.strip().lower())
        result = self.dictionary.get(key, [])
        return ([result] if isinstance(result, str) else result)[:topn]
