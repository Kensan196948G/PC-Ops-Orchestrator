"""Extra coverage tests for routes/groups.py.

Targets uncovered lines:
- create_group: pc_names loop with valid PC (79), pc_name not found (78)
- update_group: no body (112), duplicate name (122), pc_names update (129-142)
- add_pc_to_group: not found (174), no pc_name (179), success + duplicate (185-197)
- remove_pc_from_group: success and not-in-group (208-223)
- create_group_task: not found (237), no body (241), command validation (256-259),
  success loop (265-289)
"""

import json
import sys
import os
import uuid

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from extensions import db
from auth import hash_password
from models import PC, User

app = create_app("testing")
client = app.test_client()

_admin_token = None
_viewer_token = None
_unique = uuid.uuid4().hex[:8]


def setup_module():
    global _admin_token, _viewer_token
    with app.app_context():
        db.create_all()
        for username, role, password in [
            (f"admin_gr_{_unique}", "admin", "AdminGr1!"),
            (f"viewer_gr_{_unique}", "viewer", "ViewerGr1!"),
        ]:
            if not User.query.filter_by(username=username).first():
                db.session.add(User(
                    username=username,
                    password_hash=hash_password(password),
                    role=role,
                ))
        db.session.commit()

    _admin_token = _login(f"admin_gr_{_unique}", "AdminGr1!")
    _viewer_token = _login(f"viewer_gr_{_unique}", "ViewerGr1!")


def _login(username, password):
    r = client.open(
        "/api/auth/login",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"username": username, "password": password}),
    )
    return json.loads(r.data)["token"]


def req(method, path, token=None, data=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data) if data is not None else None
    return client.open(path, method=method, headers=headers, data=body)


def _create_pc(suffix):
    with app.app_context():
        pc = PC(pc_name=f"TestPC-gr-{suffix}-{_unique}")
        db.session.add(pc)
        db.session.commit()
        return pc.id, pc.pc_name


def _create_group(suffix, pc_names=None):
    payload = {
        "name": f"TestGroup-{suffix}-{_unique}",
        "description": "test",
    }
    if pc_names:
        payload["pc_names"] = pc_names
    r = req("POST", "/api/groups", token=_admin_token, data=payload)
    assert r.status_code == 201, f"group create failed: {r.data}"
    return json.loads(r.data)["group"]["id"]


# ── create_group: pc_names loop (lines 75-79) ────────────────────────


def test_create_group_with_valid_pc():
    """pc_names with existing PC → 201, PC appended (line 79)."""
    _, pc_name = _create_pc("cgpc1")
    r = req("POST", "/api/groups", token=_admin_token, data={
        "name": f"GroupWithPC-{_unique}",
        "pc_names": [pc_name],
    })
    assert r.status_code == 201
    data = json.loads(r.data)
    group_id = data["group"]["id"]
    pc_names_in_group = [p["pc_name"] for p in data["group"]["pcs"]]
    assert pc_name in pc_names_in_group
    req("DELETE", f"/api/groups/{group_id}", token=_admin_token)


def test_create_group_with_unknown_pc():
    """pc_names with unknown PC → 400 (line 78)."""
    r = req("POST", "/api/groups", token=_admin_token, data={
        "name": f"GroupBadPC-{_unique}",
        "pc_names": [f"NoSuchPC-{_unique}"],
    })
    assert r.status_code == 400
    assert "見つかりません" in json.loads(r.data)["error"]


def test_create_group_pc_names_not_list():
    """pc_names not a list → 400 (line 74)."""
    r = req("POST", "/api/groups", token=_admin_token, data={
        "name": f"GroupNotList-{_unique}",
        "pc_names": "not-a-list",
    })
    assert r.status_code == 400
    assert "pc_names" in json.loads(r.data)["error"]


# ── update_group (lines 112, 122, 129-142) ───────────────────────────


def test_update_group_no_body():
    """PUT without body → 400 or 415 (line 112)."""
    group_id = _create_group("upd1")
    r = client.open(
        f"/api/groups/{group_id}",
        method="PUT",
        headers={"Authorization": f"Bearer {_admin_token}"},
    )
    assert r.status_code in (400, 415)
    req("DELETE", f"/api/groups/{group_id}", token=_admin_token)


def test_update_group_duplicate_name():
    """PUT with name that already exists for another group → 409 (line 122)."""
    group_id1 = _create_group("dup1")
    name2 = f"DupGroup2-{_unique}"
    group_id2 = _create_group("dup2")
    # Rename group2 to a name not yet used
    req("PUT", f"/api/groups/{group_id2}", token=_admin_token,
        data={"name": name2})

    # Now try to rename group1 to name2
    r = req("PUT", f"/api/groups/{group_id1}", token=_admin_token,
            data={"name": name2})
    assert r.status_code == 409
    req("DELETE", f"/api/groups/{group_id1}", token=_admin_token)
    req("DELETE", f"/api/groups/{group_id2}", token=_admin_token)


def test_update_group_replace_pcs():
    """PUT with pc_names replaces group membership (lines 129-142)."""
    _, pc_name1 = _create_pc("updpc1")
    _, pc_name2 = _create_pc("updpc2")
    group_id = _create_group("updpcs", pc_names=[pc_name1])

    r = req("PUT", f"/api/groups/{group_id}", token=_admin_token, data={
        "pc_names": [pc_name2],
    })
    assert r.status_code == 200
    data = json.loads(r.data)
    pc_names_in_group = [p["pc_name"] for p in data["group"]["pcs"]]
    assert pc_name2 in pc_names_in_group
    assert pc_name1 not in pc_names_in_group
    req("DELETE", f"/api/groups/{group_id}", token=_admin_token)


def test_update_group_replace_pcs_unknown_pc():
    """PUT with pc_names containing unknown PC → 400 (line 136)."""
    group_id = _create_group("updnopc")
    r = req("PUT", f"/api/groups/{group_id}", token=_admin_token, data={
        "pc_names": [f"NoSuchPC-{_unique}"],
    })
    assert r.status_code == 400
    assert "見つかりません" in json.loads(r.data)["error"]
    req("DELETE", f"/api/groups/{group_id}", token=_admin_token)


def test_update_group_pc_names_not_list():
    """PUT with pc_names not a list → 400 (line 131)."""
    group_id = _create_group("updnotlist")
    r = req("PUT", f"/api/groups/{group_id}", token=_admin_token, data={
        "pc_names": "not-a-list",
    })
    assert r.status_code == 400
    assert "pc_names" in json.loads(r.data)["error"]
    req("DELETE", f"/api/groups/{group_id}", token=_admin_token)


# ── add_pc_to_group (lines 174, 179, 185-197) ────────────────────────


def test_add_pc_to_group_not_found():
    """Group not found → 404 (line 174)."""
    r = req("POST", "/api/groups/9999999/pcs", token=_admin_token,
            data={"pc_name": "any"})
    assert r.status_code == 404


def test_add_pc_to_group_no_pc_name():
    """No pc_name in body → 400 (line 179)."""
    group_id = _create_group("addnopc")
    r = req("POST", f"/api/groups/{group_id}/pcs", token=_admin_token, data={})
    assert r.status_code == 400
    assert "pc_name" in json.loads(r.data)["error"]
    req("DELETE", f"/api/groups/{group_id}", token=_admin_token)


def test_add_pc_to_group_pc_not_found():
    """pc_name not in DB → 400 (line 183)."""
    group_id = _create_group("addpcnf")
    r = req("POST", f"/api/groups/{group_id}/pcs", token=_admin_token,
            data={"pc_name": f"NoSuchPC-{_unique}"})
    assert r.status_code == 400
    assert "見つかりません" in json.loads(r.data)["error"]
    req("DELETE", f"/api/groups/{group_id}", token=_admin_token)


def test_add_pc_to_group_success():
    """Valid PC → 200 with updated group (lines 185-197)."""
    _, pc_name = _create_pc("addpc1")
    group_id = _create_group("addpc")
    r = req("POST", f"/api/groups/{group_id}/pcs", token=_admin_token,
            data={"pc_name": pc_name})
    assert r.status_code == 200
    data = json.loads(r.data)
    pc_names_in = [p["pc_name"] for p in data["group"]["pcs"]]
    assert pc_name in pc_names_in
    req("DELETE", f"/api/groups/{group_id}", token=_admin_token)


def test_add_pc_to_group_already_member():
    """PC already in group → 409 (lines 185-188)."""
    _, pc_name = _create_pc("addpcdup")
    group_id = _create_group("addpcdup", pc_names=[pc_name])
    r = req("POST", f"/api/groups/{group_id}/pcs", token=_admin_token,
            data={"pc_name": pc_name})
    assert r.status_code == 409
    assert "既に" in json.loads(r.data)["error"]
    req("DELETE", f"/api/groups/{group_id}", token=_admin_token)


# ── remove_pc_from_group (lines 208-223) ─────────────────────────────


def test_remove_pc_from_group_not_found_group():
    """Group not found → 404 (line 210)."""
    r = req("DELETE", "/api/groups/9999999/pcs/1", token=_admin_token)
    assert r.status_code == 404


def test_remove_pc_from_group_pc_not_member():
    """PC not in group → 404 (line 214)."""
    _, pc_name = _create_pc("remnopc")
    group_id = _create_group("remnomem")
    with app.app_context():
        pc = PC.query.filter_by(pc_name=pc_name).first()
        pc_id = pc.id
    r = req("DELETE", f"/api/groups/{group_id}/pcs/{pc_id}", token=_admin_token)
    assert r.status_code == 404
    req("DELETE", f"/api/groups/{group_id}", token=_admin_token)


def test_remove_pc_from_group_success():
    """PC in group → removed, 200 (lines 216-227)."""
    _, pc_name = _create_pc("rempc1")
    group_id = _create_group("rempc", pc_names=[pc_name])
    with app.app_context():
        pc = PC.query.filter_by(pc_name=pc_name).first()
        pc_id = pc.id
    r = req("DELETE", f"/api/groups/{group_id}/pcs/{pc_id}", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "グループから PC を削除しました" in data["message"]
    req("DELETE", f"/api/groups/{group_id}", token=_admin_token)


# ── create_group_task (lines 237, 241, 256-259, 265-289) ─────────────


def test_create_group_task_group_not_found():
    """Group not found → 404 (line 237)."""
    r = req("POST", "/api/groups/9999999/tasks", token=_admin_token,
            data={"task_type": "cleanup"})
    assert r.status_code == 404


def test_create_group_task_no_body():
    """No body → 400 or 415 (line 241)."""
    group_id = _create_group("tasknobody")
    r = client.open(
        f"/api/groups/{group_id}/tasks",
        method="POST",
        headers={"Authorization": f"Bearer {_admin_token}"},
    )
    assert r.status_code in (400, 415)
    req("DELETE", f"/api/groups/{group_id}", token=_admin_token)


def test_create_group_task_invalid_task_type():
    """Invalid task_type → 400."""
    group_id = _create_group("taskinvalidtype")
    r = req("POST", f"/api/groups/{group_id}/tasks", token=_admin_token,
            data={"task_type": "invalid_type"})
    assert r.status_code == 400
    assert "task_type" in json.loads(r.data)["error"]
    req("DELETE", f"/api/groups/{group_id}", token=_admin_token)


def test_create_group_task_command_not_str():
    """command is not str → 400 (line 257)."""
    _, pc_name = _create_pc("gtcmdtype")
    group_id = _create_group("taskcmdtype", pc_names=[pc_name])
    r = req("POST", f"/api/groups/{group_id}/tasks", token=_admin_token, data={
        "task_type": "custom",
        "command": 12345,
    })
    assert r.status_code == 400
    assert "command" in json.loads(r.data)["error"]
    req("DELETE", f"/api/groups/{group_id}", token=_admin_token)


def test_create_group_task_command_too_long():
    """command > 512 chars → 400 (line 259)."""
    _, pc_name = _create_pc("gtcmdlen")
    group_id = _create_group("taskcmdlen", pc_names=[pc_name])
    r = req("POST", f"/api/groups/{group_id}/tasks", token=_admin_token, data={
        "task_type": "custom",
        "command": "A" * 513,
    })
    assert r.status_code == 400
    assert "command" in json.loads(r.data)["error"]
    req("DELETE", f"/api/groups/{group_id}", token=_admin_token)


def test_create_group_task_no_pcs():
    """Group with no PCs → 400 (line 263)."""
    group_id = _create_group("tasknopcs")
    r = req("POST", f"/api/groups/{group_id}/tasks", token=_admin_token,
            data={"task_type": "cleanup"})
    assert r.status_code == 400
    assert "PC" in json.loads(r.data)["error"]
    req("DELETE", f"/api/groups/{group_id}", token=_admin_token)


def test_create_group_task_success():
    """Valid group with PCs → 201 with tasks list (lines 265-289)."""
    _, pc_name1 = _create_pc("gtpc1")
    _, pc_name2 = _create_pc("gtpc2")
    group_id = _create_group("tasksucc", pc_names=[pc_name1, pc_name2])
    r = req("POST", f"/api/groups/{group_id}/tasks", token=_admin_token, data={
        "task_type": "diagnose",
        "priority": 3,
    })
    assert r.status_code == 201
    data = json.loads(r.data)
    assert "tasks" in data
    assert len(data["tasks"]) == 2
    for t in data["tasks"]:
        assert t["task_type"] == "diagnose"
        assert t["status"] == "pending"
    # cleanup tasks
    from models import Task
    with app.app_context():
        for t in data["tasks"]:
            task = db.session.get(Task, t["id"])
            if task:
                db.session.delete(task)
        db.session.commit()
    req("DELETE", f"/api/groups/{group_id}", token=_admin_token)


# ── list_groups: with PCs (pc_counts batch query, lines 24-34) ───────


def test_list_groups_with_pcs():
    """Groups with PCs → pc_count is non-zero in response (lines 24-34)."""
    _, pc_name = _create_pc("lgpc")
    group_id = _create_group("listpc", pc_names=[pc_name])
    r = req("GET", "/api/groups", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    group = next((g for g in data["groups"] if g["id"] == group_id), None)
    assert group is not None
    assert group["pc_count"] >= 1
    req("DELETE", f"/api/groups/{group_id}", token=_admin_token)
