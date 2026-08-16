from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from brix.domain import Profile, utc_now


class ProfileManager:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)

    def _path(self, profile_id: str) -> Path:
        if not profile_id or any(
            char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
            for char in profile_id
        ):
            raise ValueError("Invalid profile id")
        path = (self.root / profile_id).resolve()
        if self.root not in path.parents:
            raise ValueError("Invalid profile path")
        return path

    def create(self, profile_id: str, display_name: str | None = None) -> Profile:
        path = self._path(profile_id)
        if path.exists():
            raise FileExistsError(profile_id)
        (path / "user-data").mkdir(parents=True)
        (path / "downloads").mkdir()
        os.chmod(path, 0o700)
        os.chmod(path / "user-data", 0o700)
        os.chmod(path / "downloads", 0o700)
        profile = Profile(id=profile_id, display_name=display_name or profile_id)
        self._save(path, profile)
        return profile

    def get_or_create(self, profile_id: str) -> Profile:
        return self.get(profile_id) or self.create(profile_id)

    def get(self, profile_id: str) -> Profile | None:
        path = self._path(profile_id)
        metadata = path / "profile.json"
        return (
            Profile.model_validate_json(metadata.read_text("utf-8")) if metadata.exists() else None
        )

    def list(self) -> list[Profile]:
        profiles = [
            item for path in self.root.iterdir() if path.is_dir() if (item := self.get(path.name))
        ]
        return sorted(profiles, key=lambda item: item.created_at)

    def acquire(self, profile_id: str, task_id: str) -> Profile:
        profile = self.get_or_create(profile_id)
        if profile.locked_by and profile.locked_by != task_id:
            raise RuntimeError(f"Profile {profile_id!r} is already in use")
        profile.locked_by = task_id
        profile.last_used_at = utc_now()
        self._save(self._path(profile_id), profile)
        return profile

    def release(self, profile_id: str, task_id: str) -> None:
        profile = self.get(profile_id)
        if profile and profile.locked_by == task_id:
            profile.locked_by = None
            self._save(self._path(profile_id), profile)

    def delete(self, profile_id: str) -> None:
        profile = self.get(profile_id)
        if profile is None:
            raise KeyError(profile_id)
        if profile.locked_by:
            raise RuntimeError("Cannot delete a profile while it is in use")
        shutil.rmtree(self._path(profile_id))

    def user_data_dir(self, profile_id: str) -> Path:
        return self._path(profile_id) / "user-data"

    def downloads_dir(self, profile_id: str) -> Path:
        return self._path(profile_id) / "downloads"

    @staticmethod
    def _save(path: Path, profile: Profile) -> None:
        path.mkdir(parents=True, exist_ok=True)
        metadata = path / "profile.json"
        metadata.write_text(json.dumps(profile.model_dump(mode="json"), indent=2), encoding="utf-8")
        os.chmod(path, 0o700)
        os.chmod(metadata, 0o600)
